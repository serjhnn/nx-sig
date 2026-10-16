# alerts: price alerts for the basetrades, checked by
# one background process
#
#   python scripts/alerts.py run    the process ('run
#                                   alert' in the shell
#                                   starts it)
#   python scripts/alerts.py        run the tests
#
# an alert is a change from the buying price of every
# basetrade: 'down 10 percent' is 90 for a basetrade
# bought at 100. the process sends a Telegram message
# each time a stock's price crosses the level: when it
# reaches 90, and again after the price went back over
# it and falls to 90 once more. the price has to go
# back REARM_PERCENT of the buying price past the level
# first, so a price that wobbles around it doesn't send
# a message every check. a new basetrade (a new buying
# price) starts the stock over.
#
# the stocks past each alert are saved in
# alerts_status.json, so after a restart nothing is
# sent twice. the price is checked every config
# "ladder_interval" seconds (default 30), like the
# ladders. logs: {storage_dir}/logs/alerts.log
#
# public functions:
#   create(target, direction, percent)
#       check and save a new alert, return its Id
#   remove(alert_id)
#       delete it, return it or None; stops the process
#       when no alert is left
#   alerts_get_all()
#       the saved alerts
#   level(base, alert)
#       the price of alert for a buying price
#   past(alert, level, price), rearmed(...)
#       the crossing math
#   check(alerts, basetrades, prices, past_now)
#       one check: the messages to send
#   basetrade_levels(basetrades, prices)
#       each alert's level per basetrade, for
#       'ls basetrades'
#   start(force=False), stop(), running_pid()
#       the process, see ladder.start
#   status()
#       its heartbeat, or None
#   run()
#       the process: check the prices and notify

import logging
import os
import signal
import sys
import time
from datetime import datetime

import requests

import ladder
import storage
import tasks_owner
from storage import (
    ROOT_DIR,
    alert_add,
    alert_delete,
    alerts_get_all,
    alerts_status_get,
    alerts_status_set,
    basetrades_get_all,
)
from trade_engine import get_latest_prices
from telegram_notify import notify

SCRIPT = os.path.join(ROOT_DIR, "scripts", "alerts.py")
TARGETS = ("basetrades",)
DIRECTIONS = ladder.DIRECTIONS
INTERVAL = ladder.INTERVAL
STALE_SECONDS = ladder.STALE_SECONDS
# how far, in percent of the buying price, the price
# must go back past the level before it is sent again
REARM_PERCENT = 1

log = logging.getLogger("alerts")


class AlertError(Exception):
    """an alert can't be saved, or the process can't be
    started; the text says why"""


def create(target, direction, percent):
    if target not in TARGETS:
        raise AlertError(
            f"alerts are for {'/'.join(TARGETS)}"
        )
    if direction not in DIRECTIONS:
        raise AlertError("direction must be down or up")
    if percent <= 0:
        raise AlertError("percent must be positive")
    if direction == "down" and percent >= 100:
        raise AlertError(
            "a price can't go down 100 percent or more"
        )
    return alert_add(target, direction, percent)


def remove(alert_id):
    """delete alert <alert_id>, return it (None if there
    is none) and stop the process if no alert is left"""
    deleted = alert_delete(alert_id)
    if deleted is not None and not alerts_get_all():
        stop()
    return deleted


def describe(alert):
    """'down 10%'"""
    return f"{alert['Direction']} {alert['Percent']:g}%"


def level(base, alert):
    sign = -1 if alert["Direction"] == "down" else 1
    return round(
        base * (1 + sign * alert["Percent"] / 100), 6
    )


def past(alert, level, price):
    """True if price has reached the alert's level"""
    if alert["Direction"] == "down":
        return price <= level
    return price >= level


def rearmed(alert, level, base, price):
    """True if price went back far enough past the level
    to send the alert again when it crosses it"""
    margin = base * REARM_PERCENT / 100
    if alert["Direction"] == "down":
        return price >= level + margin
    return price <= level - margin


def check(alerts, basetrades, prices, past_now):
    """
    one check of every alert against the basetrades;
    past_now is {alert id: {stock: buying price}} of the
    stocks past each alert (alerts_status.json). return
    (past_now with the stocks that went back, the
    stocks of removed alerts and basetrades dropped,
    [(alert id, stock, buying price, text)] to send)
    """
    kept = {}
    messages = []
    for alert in alerts:
        key = str(alert["Id"])
        before = past_now.get(key) or {}
        stocks = {}
        for b in basetrades:
            name, base = b["Stock"], b["Price"]
            price = prices.get(name)
            at = level(base, alert)
            # a new basetrade starts the stock over
            was_past = before.get(name) == base
            if price is None:
                if was_past:
                    stocks[name] = base
                continue
            if was_past and not rearmed(
                alert, at, base, price
            ):
                stocks[name] = base
            elif not was_past and past(alert, at, price):
                change = (price - base) / base * 100
                messages.append(
                    (
                        alert["Id"],
                        name,
                        base,
                        f"{name} {change:+.1f}% at "
                        f"{price:.2f}, bought at {base:g} "
                        f"(alert {alert['Id']}: "
                        f"{describe(alert)})",
                    )
                )
        kept[key] = stocks
    return kept, messages


def basetrade_levels(basetrades, prices):
    """[(alert, [(stock, level, past)])] of every alert
    for basetrades, past True if the current price has
    reached the level"""
    rows = []
    for alert in alerts_get_all():
        if alert["For"] != "basetrades":
            continue
        stocks = []
        for b in basetrades:
            at = level(b["Price"], alert)
            price = prices.get(b["Stock"])
            stocks.append(
                (
                    b["Stock"],
                    at,
                    price is not None
                    and past(alert, at, price),
                )
            )
        rows.append((alert, stocks))
    return rows


def status():
    return alerts_status_get()


def running_pid():
    pid = (alerts_status_get() or {}).get("pid")
    if pid and ladder.process_runs(pid, "alerts.py", "run"):
        return pid
    return None


def start(force=False):
    """
    start the alerts process and return its pid; raise
    AlertError if there are no alerts, it already runs,
    another device runs the background tasks (unless
    force) or it stops right away
    """
    if not alerts_get_all():
        raise AlertError("no alerts, see 'help add alert'")
    pid = running_pid()
    if pid:
        raise AlertError(
            f"the alerts are already checked (pid {pid})"
        )
    try:
        tasks_owner.claim(force)
    except tasks_owner.OwnerError as e:
        raise AlertError(str(e)) from None
    process = ladder.spawn([SCRIPT, "run"], _out_path())
    # so running_pid() knows it before the process writes
    # its first heartbeat
    _status(process.pid, _now(), "starting")
    deadline = time.monotonic() + ladder.START_CHECK_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            ladder.release_if_idle()
            raise AlertError(
                "the alerts process stopped right after "
                "starting: "
                + ladder.last_line(
                    [_out_path(), _log_path()]
                )
            )
        time.sleep(0.2)
    return process.pid


def stop():
    """stop the alerts process (SIGTERM, then SIGKILL),
    True if it was running"""
    pid = running_pid()
    if not pid:
        return False
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + ladder.STOP_WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            os.waitpid(pid, os.WNOHANG)
        except (ChildProcessError, OSError):
            pass
        if not running_pid():
            break
        time.sleep(0.2)
    else:
        os.kill(pid, signal.SIGKILL)
        _status(pid, None, "stopped")
    ladder.release_if_idle()
    return True


def _out_path():
    return os.path.join(
        storage.DB_DIR, "logs", "alerts.out"
    )


def _log_path():
    return os.path.join(
        storage.DB_DIR, "logs", "alerts.log"
    )


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _status(pid, started, state, past_now=None):
    """write the heartbeat that 'ls tasks' shows, with
    the stocks past each alert"""
    previous = alerts_status_get() or {}
    try:
        alerts_status_set(
            {
                "pid": pid,
                "started": started
                or previous.get("started"),
                "updated": _now(),
                "state": state,
                "past": (
                    previous.get("past") or {}
                    if past_now is None
                    else past_now
                ),
            }
        )
    except Exception:
        log.exception("could not write the alerts status")


# ---------------- the alerts process ----------------


def run():
    """check the prices every INTERVAL seconds and
    notify each crossing, until SIGTERM or Ctrl+C"""
    signal.signal(signal.SIGTERM, _stop_on_signal)
    signal.signal(signal.SIGINT, signal.default_int_handler)
    ladder.setup_logging(_log_path())
    pid = os.getpid()
    started = _now()
    log.info("alerts starting, pid %s", pid)
    _status(pid, started, "starting")
    try:
        while True:
            if tasks_owner.lost():
                log.warning(
                    "%s took over the background "
                    "tasks, alerts stop",
                    tasks_owner.describe(
                        tasks_owner.owner()
                    ),
                )
                _status(pid, started, "taken over")
                break
            alerts = alerts_get_all()
            if not alerts:
                log.info("no alerts left, alerts end")
                _status(pid, started, "done")
                break
            state, past_now = _check(alerts)
            _status(pid, started, state, past_now)
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        _status(pid, started, "stopped")
        log.info("alerts stopped")
    except Exception:
        log.critical("alerts crashed", exc_info=True)
        _status(pid, started, "crashed")
        sys.exit(1)
    finally:
        ladder.release_if_idle(alerts_ending=True)


def _check(alerts):
    """one check of the prices; return (state, the
    stocks past each alert)"""
    past_now = (alerts_status_get() or {}).get("past") or {}
    try:
        prices = get_latest_prices()
    except (
        requests.RequestException,
        KeyError,
        ValueError,
    ) as e:
        log.warning("price request failed: %s", e)
        return "no price", past_now
    past_now, messages = check(
        alerts, basetrades_get_all(), prices, past_now
    )
    state = "waiting"
    for alert_id, name, base, text in messages:
        try:
            notify(text)
        except Exception as e:
            # not saved as past, so it is sent again at
            # the next check
            log.warning("could not send %r: %s", text, e)
            state = "no notify"
            continue
        past_now[str(alert_id)][name] = base
        log.info("sent: %s", text)
    return state, past_now


def _stop_on_signal(signum, frame):
    # handled like Ctrl+C: the heartbeat says 'stopped'
    raise KeyboardInterrupt


if __name__ == "__main__" and sys.argv[1:] == ["run"]:
    run()

elif __name__ == "__main__":
    import tempfile
    import unittest
    from unittest import mock

    DOWN = {"Id": 1, "Direction": "down", "Percent": 10}
    UP = {"Id": 2, "Direction": "up", "Percent": 20}

    def bought(price):
        return [{"Stock": "MRVU", "Price": price}]

    class LevelsTest(unittest.TestCase):
        def test_level(self):
            self.assertEqual(level(100, DOWN), 90)
            self.assertEqual(level(100, UP), 120)
            self.assertEqual(level(20.5, DOWN), 18.45)

        def test_past(self):
            self.assertFalse(past(DOWN, 90, 90.01))
            self.assertTrue(past(DOWN, 90, 90))
            self.assertTrue(past(DOWN, 90, 50))
            self.assertFalse(past(UP, 120, 119.99))
            self.assertTrue(past(UP, 120, 120))

        def test_rearmed(self):
            # 1% of the buying price 100 past 90
            self.assertFalse(rearmed(DOWN, 90, 100, 90.99))
            self.assertTrue(rearmed(DOWN, 90, 100, 91))
            self.assertFalse(rearmed(UP, 120, 100, 119.5))
            self.assertTrue(rearmed(UP, 120, 100, 119))

    class CheckTest(unittest.TestCase):
        def step(self, price, base=100, alerts=(DOWN,)):
            """one check at price, return the stocks
            the messages are about"""
            self.past, messages = check(
                list(alerts),
                bought(base),
                {"MRVU": price} if price else {},
                self.past,
            )
            # as if every message was sent
            for alert_id, name, base, _ in messages:
                self.past[str(alert_id)][name] = base
            return [m[1] for m in messages]

        def setUp(self):
            self.past = {}

        def test_every_crossing(self):
            self.assertEqual(self.step(95), [])
            self.assertEqual(self.step(89.5), ["MRVU"])
            # still past: no new message
            self.assertEqual(self.step(85), [])
            # back over 90 but within 1%: no new one
            self.assertEqual(self.step(90.5), [])
            self.assertEqual(self.step(89), [])
            # back over 91 and down again: sent again
            self.assertEqual(self.step(92), [])
            self.assertEqual(self.past, {"1": {}})
            self.assertEqual(self.step(90), ["MRVU"])

        def test_text(self):
            _, messages = check(
                [DOWN, UP],
                bought(100),
                {"MRVU": 89.5},
                {},
            )
            self.assertEqual(
                [m[3] for m in messages],
                [
                    "MRVU -10.5% at 89.50, bought at 100 "
                    "(alert 1: down 10%)"
                ],
            )

        def test_already_past_is_sent(self):
            self.assertEqual(self.step(50), ["MRVU"])

        def test_new_basetrade_starts_over(self):
            self.step(89)
            # bought again at 95: past its 85.5? no
            self.assertEqual(self.step(89, base=95), [])
            self.assertEqual(self.past, {"1": {}})
            self.assertEqual(
                self.step(85, base=95), ["MRVU"]
            )

        def test_no_price_keeps_the_state(self):
            self.step(89)
            self.assertEqual(self.step(None), [])
            self.assertEqual(
                self.past, {"1": {"MRVU": 100}}
            )

        def test_removed_alert_is_dropped(self):
            self.past = {"7": {"MRVU": 100}}
            self.step(95)
            self.assertEqual(self.past, {"1": {}})

    class ProcessTest(unittest.TestCase):
        def setUp(self):
            self._tmp = tempfile.TemporaryDirectory()
            self._db_dir = storage.DB_DIR
            storage.DB_DIR = self._tmp.name
            self.sent = []
            self.prices = {"MRVU": 89.0}
            for p in (
                mock.patch(
                    f"{__name__}.notify", self.sent.append
                ),
                mock.patch(
                    f"{__name__}.get_latest_prices",
                    lambda: dict(self.prices),
                ),
            ):
                p.start()

        def tearDown(self):
            mock.patch.stopall()
            storage.DB_DIR = self._db_dir
            self._tmp.cleanup()

        def test_check_saves_what_was_sent(self):
            storage.basetrade_set("MRVU", 100.0, 1)
            create("basetrades", "down", 10)
            state, past_now = _check(alerts_get_all())
            self.assertEqual(state, "waiting")
            self.assertEqual(len(self.sent), 1)
            self.assertEqual(past_now, {"1": {"MRVU": 100}})
            _status(1, _now(), state, past_now)
            # the next check knows it was sent
            _check(alerts_get_all())
            self.assertEqual(len(self.sent), 1)

        def test_failed_notify_is_sent_again(self):
            def fail(text):
                raise RuntimeError("offline")

            storage.basetrade_set("MRVU", 100.0, 1)
            create("basetrades", "down", 10)
            with mock.patch(f"{__name__}.notify", fail):
                state, past_now = _check(alerts_get_all())
            self.assertEqual(state, "no notify")
            self.assertEqual(past_now, {"1": {}})

        def test_create_checks(self):
            for args in (
                ("stocks", "down", 10),
                ("basetrades", "left", 10),
                ("basetrades", "up", 0),
                ("basetrades", "down", 100),
            ):
                with self.assertRaises(AlertError):
                    create(*args)
            self.assertEqual(
                create("basetrades", "up", 150), 1
            )

        def test_start_without_alerts(self):
            with self.assertRaises(AlertError):
                start()

        def test_basetrade_levels(self):
            create("basetrades", "down", 10)
            rows = basetrade_levels(
                [
                    {"Stock": "MRVU", "Price": 100.0},
                    {"Stock": "SOXL", "Price": 20.0},
                ],
                {"MRVU": 89.0},
            )
            self.assertEqual(
                [(a["Id"], s) for a, s in rows],
                [
                    (
                        1,
                        [
                            ("MRVU", 90.0, True),
                            ("SOXL", 18.0, False),
                        ],
                    )
                ],
            )

    # the warnings of the failed notify
    logging.disable(logging.WARNING)
    unittest.main()

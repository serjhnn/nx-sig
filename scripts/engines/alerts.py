# alerts: the alerts engine, price alerts for the
# basetrades and the gain of the held stocks, checked by
# one background process, services/alert_service.py
#
#   python tests/test_alerts.py     the tests
#
# an alert is a change from the buying price of every
# basetrade: 'down 10 percent' is 90 for a basetrade
# bought at 100. the process sends a message (see
# notifiers/notifier.py) each time a stock's price
# crosses the level: when it reaches 90, and again
# after the price went back over it and falls to 90
# once more. the price has to go back REARM_PERCENT of
# the buying price past the level first, so a price
# that wobbles around it doesn't send a message every
# check. a new basetrade (a new buying price) starts
# the stock over.
#
# a gain alert is the gain of a held stock, from its
# trades like in xtop: 'gain TSMX 100' when the gain of
# TSMX reaches +100, 'gain all 10 percent' when a held
# stock is 10% over its average buy price, a negative
# number for a loss. it becomes a price level too (avg
# + 100 / count, avg * 1.1), checked the same way; a
# trade that changes the count or the average starts
# the stock over.
#
# the stocks past each alert are saved in
# alerts_status.json, so after a restart nothing is
# sent twice. the price is checked every config
# "timing" "alert_interval" seconds (default 30).
# logs: {storage_dir}/logs/alerts.log
#
# public functions:
#   create(target, direction, percent)
#       check and save a new basetrades alert, return
#       its Id
#   create_gain(stock, value, percent=False)
#       check and save a new gain alert, value the
#       amount (or the % with percent), negative for a
#       loss; stock a name or "all"; return its Id
#   remove(alert_id)
#       delete it, return it or None; stops the process
#       when no alert is left
#   alerts_get_all()
#       the saved alerts
#   level(base, alert)
#       the price of alert for a buying price
#   gain_level(alert, count, avg)
#       the price of a gain alert for a position
#   past(alert, level, price), rearmed(...)
#       the crossing math
#   check(alerts, basetrades, positions, prices,
#         past_now)
#       one check: the messages to send
#   basetrade_levels(basetrades, prices)
#       each alert's level per basetrade, for
#       'ls basetrades'
#   gain_levels(prices)
#       each gain alert's level per held stock, for
#       'xtop'
#   start(force=False), stop(), running_pid()
#       the process; only on the device that runs the
#       background tasks (tasks_owner.py), force takes
#       them over (the helpers are in process.py)
#   status()
#       its heartbeat, or None
#   save_status(pid, started, state, past_now=None)
#       write the heartbeat that 'ls tasks' shows
#   log_path()
#       the log file of the process

import logging
import os
import signal
import time
from datetime import datetime

import config
import process
import storage
import tasks_owner
from storage import (
    ROOT_DIR,
    alert_add,
    alert_delete,
    alerts_get_all,
    alerts_status_get,
    alerts_status_set,
    Stock,
)
from engines import trades

SERVICE = "alert_service.py"
SCRIPT = os.path.join(
    ROOT_DIR, "scripts", "services", SERVICE
)
TARGETS = ("basetrades", "gain")
DIRECTIONS = ("down", "up")
INTERVAL = config.interval("alert_interval")
# 'ls alerts' shows 'no reply' when the heartbeat is
# older than this
STALE_SECONDS = max(3 * INTERVAL, 120)
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


def create_gain(stock, value, percent=False):
    if stock != "all" and stock not in Stock.__members__:
        raise AlertError(f"unknown stock '{stock}'")
    if value == 0:
        raise AlertError("the gain can't be 0")
    if percent and value <= -100:
        raise AlertError(
            "a loss can't be 100 percent or more"
        )
    direction = "down" if value < 0 else "up"
    if percent:
        return alert_add(
            "gain", direction, abs(value), stock=stock
        )
    return alert_add(
        "gain", direction, stock=stock, amount=abs(value)
    )


def remove(alert_id):
    """delete alert <alert_id>, return it (None if there
    is none) and stop the process if no alert is left"""
    deleted = alert_delete(alert_id)
    if deleted is not None and not alerts_get_all():
        stop()
    return deleted


def describe(alert):
    """'down 10%' of a basetrades alert, 'TSMX +100' or
    'all -10%' of a gain alert"""
    if alert.get("For", "basetrades") == "basetrades":
        return f"{alert['Direction']} {alert['Percent']:g}%"
    sign = "-" if alert["Direction"] == "down" else "+"
    if alert["Percent"] is not None:
        value = f"{alert['Percent']:g}%"
    else:
        value = f"{alert['Amount']:g}"
    return f"{alert['Stock']} {sign}{value}"


def level(base, alert):
    sign = -1 if alert["Direction"] == "down" else 1
    return round(
        base * (1 + sign * alert["Percent"] / 100), 6
    )


def gain_level(alert, count, avg):
    """the price at which a position of count stocks
    bought at avg on average reaches the gain alert"""
    if alert["Percent"] is not None:
        return level(avg, alert)
    sign = -1 if alert["Direction"] == "down" else 1
    return round(avg + sign * alert["Amount"] / count, 6)


def positions_get():
    """[(stock name, count, average buy price)] of the
    stocks held"""
    positions = []
    for stock in Stock:
        count, avg = trades.total(stock)
        if count > 0:
            positions.append((stock.name, count, avg))
    return positions


def _targets(alert, basetrades, positions):
    """[(stock, base, key, level)] the alert checks:
    base is the buying price (for the re-arm margin),
    key what is saved for a stock past the level, so a
    new key starts the stock over"""
    if alert.get("For", "basetrades") == "basetrades":
        return [
            (b["Stock"], b["Price"], b["Price"], at)
            for b in basetrades
            for at in [level(b["Price"], alert)]
        ]
    return [
        (name, avg, at, at)
        for name, count, avg in positions
        if alert["Stock"] in ("all", name)
        for at in [gain_level(alert, count, avg)]
    ]


def _text(alert, name, base, price, positions):
    """the message of a crossing"""
    label = f"(alert {alert['Id']}: "
    if alert.get("For", "basetrades") == "basetrades":
        change = (price - base) / base * 100
        return (
            f"{name} {change:+.1f}% at {price:.2f}, "
            f"bought at {base:g} {label}"
            f"{describe(alert)})"
        )
    count = next(c for n, c, _ in positions if n == name)
    gain = (price - base) * count
    change = (price - base) / base * 100
    return (
        f"{name} gain {gain:+.2f} ({change:+.1f}%) at "
        f"{price:.2f} {label}gain {describe(alert)})"
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


def check(alerts, basetrades, positions, prices, past_now):
    """
    one check of every alert against the basetrades and
    the positions, [(stock, count, avg)]; past_now is
    {alert id: {stock: key}} of the stocks past each
    alert (alerts_status.json), the key the buying price
    of a basetrade or the level of a gain alert. return
    (past_now with the stocks that went back, the stocks
    of removed alerts, basetrades and positions dropped,
    [(alert id, stock, key, text)] to send)
    """
    kept = {}
    messages = []
    for alert in alerts:
        before = past_now.get(str(alert["Id"])) or {}
        stocks = {}
        for name, base, key, at in _targets(
            alert, basetrades, positions
        ):
            price = prices.get(name)
            # a new basetrade or trade starts it over
            was_past = before.get(name) == key
            if price is None:
                if was_past:
                    stocks[name] = key
                continue
            if was_past and not rearmed(
                alert, at, base, price
            ):
                stocks[name] = key
            elif not was_past and past(alert, at, price):
                messages.append(
                    (
                        alert["Id"],
                        name,
                        key,
                        _text(
                            alert,
                            name,
                            base,
                            price,
                            positions,
                        ),
                    )
                )
        kept[str(alert["Id"])] = stocks
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


def gain_levels(prices):
    """[(alert, [(stock, level, past)])] of every gain
    alert for the held stocks, past True if the current
    price has reached the level"""
    positions = positions_get()
    rows = []
    for alert in alerts_get_all():
        if alert["For"] != "gain":
            continue
        stocks = []
        for name, _, _, at in _targets(
            alert, [], positions
        ):
            price = prices.get(name)
            stocks.append(
                (
                    name,
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
    if pid and process.process_runs(pid, SERVICE, "run"):
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
    child = process.spawn([SCRIPT, "run"], _out_path())
    # so running_pid() knows it before the process writes
    # its first heartbeat
    save_status(child.pid, _now(), "starting")
    deadline = (
        time.monotonic() + process.START_CHECK_SECONDS
    )
    while time.monotonic() < deadline:
        if child.poll() is not None:
            process.release_if_idle()
            raise AlertError(
                "the alerts process stopped right after "
                "starting: "
                + process.last_line(
                    [_out_path(), log_path()]
                )
            )
        time.sleep(0.2)
    return child.pid


def stop():
    """stop the alerts process (SIGTERM, then SIGKILL),
    True if it was running"""
    pid = running_pid()
    if not pid:
        return False
    if not process.kill(pid, signal.SIGTERM):
        process.release_if_idle()
        return False
    deadline = time.monotonic() + process.STOP_WAIT_SECONDS
    while time.monotonic() < deadline:
        process.reap(pid)
        if not running_pid():
            break
        time.sleep(0.2)
    else:
        process.kill(pid, signal.SIGKILL)
        save_status(pid, None, "stopped")
    process.release_if_idle()
    return True


def _out_path():
    return os.path.join(
        storage.DB_DIR, "logs", "alerts.out"
    )


def log_path():
    return os.path.join(
        storage.DB_DIR, "logs", "alerts.log"
    )


def _now():
    return datetime.now().isoformat(timespec="seconds")


def save_status(pid, started, state, past_now=None):
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

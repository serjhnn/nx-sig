# ladder: price-step alerts for one stock, every ladder
# runs as its own process
#
#   python scripts/ladder.py <id>   run saved ladder <id>
#                                   ('run ladder' in the
#                                   shell starts it)
#   python scripts/ladder.py        run the tests
#
# a ladder sends a Telegram message each time the price
# passes its next level: 'SOXL down 10 from 100' at 90,
# 80, 70, ... When the price jumps over several levels
# between two checks, one message names the farthest.
# the last level sent is saved in ladders.csv, so after
# a restart no level is sent twice. a down ladder ends
# when its next level would be 0 or less.
#
# the price is checked every config "timing"
# "ladder_interval" seconds (default 30). heartbeat:
# ladders_status.json, logs:
# {storage_dir}/logs/ladder_<id>.log
#
# public functions:
#   create(stock_name, direction, step, from_price)
#       check and save a new ladder, return its Id
#   start(ladder_id, force=False)
#       start the ladder's process, return its pid;
#       only on the device that runs the background
#       tasks (tasks_owner.py), force takes them over
#   stop(ladder_id)
#       stop it, True if it was running
#   remove(ladder_id)
#       stop it if it runs, delete it and its logs
#   running_pid(ladder_id)
#       pid of its process, or None
#   next_level(ladder), passed_level(ladder, price)
#       the level math
#   run(ladder_id)
#       the process: check the price and notify
#
# the process helpers (spawn, release_if_idle, ...) are
# in process.py

import glob
import logging
import math
import os
import signal
import sys
import time
from datetime import datetime

import requests

import process
import storage
import tasks_owner
from storage import (
    ROOT_DIR,
    ladder_add,
    ladder_delete,
    ladder_get,
    ladder_set_last,
    ladder_status_get,
    ladder_status_set,
)
from trade_engine import get_latest_prices
from telegram_notify import notify

SCRIPT = os.path.join(ROOT_DIR, "scripts", "ladder.py")
DIRECTIONS = ("down", "up")
INTERVAL = process.interval("ladder_interval")
# 'ls tasks' shows a ladder as 'no reply' when its
# heartbeat is older than this
STALE_SECONDS = max(3 * INTERVAL, 120)
# float rounding of the levels
EPS = 1e-9

log = logging.getLogger("ladder")


class LadderError(Exception):
    """a ladder can't be saved, started or stopped; the
    text says why"""


def create(stock_name, direction, step, from_price):
    if direction not in DIRECTIONS:
        raise LadderError("direction must be down or up")
    if step <= 0 or from_price <= 0:
        raise LadderError("step and price must be positive")
    if direction == "down" and step >= from_price:
        raise LadderError(
            "a down ladder needs a step smaller than "
            "its price"
        )
    return ladder_add(
        stock_name, direction, step, from_price
    )


def next_level(ladder):
    """the level the ladder notifies next"""
    sign = -1 if ladder["Direction"] == "down" else 1
    return round(ladder["Last"] + sign * ladder["Step"], 6)


def passed_level(ladder, price):
    """the farthest level the price has passed, or None
    if it hasn't reached the next level yet"""
    step, last = ladder["Step"], ladder["Last"]
    if ladder["Direction"] == "down":
        moved = last - price
    else:
        moved = price - last
    steps = math.floor(moved / step + EPS)
    if steps < 1:
        return None
    sign = -1 if ladder["Direction"] == "down" else 1
    return round(last + sign * steps * step, 6)


def running_pid(ladder_id):
    status = ladder_status_get(ladder_id) or {}
    pid = status.get("pid")
    if pid and process.process_runs(
        pid, "ladder.py", ladder_id
    ):
        return pid
    return None


def start(ladder_id, force=False):
    """
    start ladder <ladder_id> as its own process and
    return its pid; raise LadderError if it doesn't
    exist, already runs, another device runs the
    background tasks (unless force) or it stops right
    away
    """
    if ladder_get(ladder_id) is None:
        raise LadderError(
            f"no ladder {ladder_id}, see 'ls ladders'"
        )
    pid = running_pid(ladder_id)
    if pid:
        raise LadderError(
            f"ladder {ladder_id} is already running "
            f"(pid {pid})"
        )
    try:
        tasks_owner.claim(force)
    except tasks_owner.OwnerError as e:
        raise LadderError(str(e)) from None
    child = process.spawn(
        [SCRIPT, str(ladder_id)], _out_path(ladder_id)
    )
    # so running_pid() knows it before the process writes
    # its first heartbeat
    ladder_status_set(
        ladder_id,
        {
            "pid": child.pid,
            "started": _now(),
            "updated": _now(),
            "state": "starting",
        },
    )
    # catch a crash at start, e.g. a missing package
    deadline = (
        time.monotonic() + process.START_CHECK_SECONDS
    )
    while time.monotonic() < deadline:
        if child.poll() is not None:
            process.release_if_idle()
            raise LadderError(
                f"ladder {ladder_id} stopped right after "
                "starting: "
                + process.last_line(
                    [
                        _out_path(ladder_id),
                        _log_path(ladder_id),
                    ]
                )
            )
        time.sleep(0.2)
    return child.pid


def stop(ladder_id):
    """
    stop the process of ladder <ladder_id> (SIGTERM, then
    SIGKILL after STOP_WAIT_SECONDS), True if it was
    running; the ladder stays saved
    """
    if ladder_get(ladder_id) is None:
        raise LadderError(
            f"no ladder {ladder_id}, see 'ls ladders'"
        )
    pid = running_pid(ladder_id)
    if not pid:
        return False
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + process.STOP_WAIT_SECONDS
    while time.monotonic() < deadline:
        process.reap(pid)
        if not running_pid(ladder_id):
            break
        time.sleep(0.2)
    else:
        os.kill(pid, signal.SIGKILL)
        _status(ladder_id, pid, None, "stopped")
    process.release_if_idle()
    return True


def remove(ladder_id):
    """
    stop ladder <ladder_id> if it runs, delete it from
    ladders.csv and delete its log files; True if it was
    running
    """
    was_running = stop(ladder_id)
    ladder_delete(ladder_id)
    logs = os.path.join(
        storage.DB_DIR, "logs", f"ladder_{ladder_id}."
    )
    # ladder_<id>.out, .log and the rotated .log.1, ...
    for path in glob.glob(glob.escape(logs) + "*"):
        try:
            os.remove(path)
        except OSError:
            pass
    return was_running


def _out_path(ladder_id):
    return os.path.join(
        storage.DB_DIR, "logs", f"ladder_{ladder_id}.out"
    )


def _log_path(ladder_id):
    return os.path.join(
        storage.DB_DIR, "logs", f"ladder_{ladder_id}.log"
    )


def _now():
    return datetime.now().isoformat(timespec="seconds")


# ---------------- the ladder process ----------------


def run(ladder_id):
    """check the price every INTERVAL seconds and notify
    each level passed, until SIGTERM or Ctrl+C"""
    signal.signal(signal.SIGTERM, _stop_on_signal)
    signal.signal(signal.SIGINT, signal.default_int_handler)
    process.setup_logging(_log_path(ladder_id))
    ladder = ladder_get(ladder_id)
    if ladder is None:
        log.error("no ladder %s in ladders.csv", ladder_id)
        sys.exit(1)
    pid = os.getpid()
    started = _now()
    log.info(
        "ladder %s starting, pid %s: %s %s every %g "
        "from %g, next level %g",
        ladder_id,
        pid,
        ladder["Stock"],
        ladder["Direction"],
        ladder["Step"],
        ladder["From"],
        next_level(ladder),
    )
    _status(ladder_id, pid, started, "starting")
    try:
        while True:
            if tasks_owner.lost():
                log.warning(
                    "%s took over the background "
                    "tasks, ladder %s stops",
                    tasks_owner.describe(
                        tasks_owner.owner()
                    ),
                    ladder_id,
                )
                _status(
                    ladder_id, pid, started, "taken over"
                )
                break
            if next_level(ladder) <= 0:
                log.info("no levels left, ladder ends")
                _status(ladder_id, pid, started, "done")
                break
            state, price = _check(ladder)
            _status(ladder_id, pid, started, state, price)
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        _status(ladder_id, pid, started, "stopped")
        log.info("ladder %s stopped", ladder_id)
    except Exception:
        log.critical(
            "ladder %s crashed", ladder_id, exc_info=True
        )
        _status(ladder_id, pid, started, "crashed")
        sys.exit(1)
    finally:
        process.release_if_idle(ending_id=ladder_id)


def _check(ladder):
    """one check of the price; return (state, price)"""
    try:
        prices = get_latest_prices()
    except (
        requests.RequestException,
        KeyError,
        ValueError,
    ) as e:
        log.warning("price request failed: %s", e)
        return "no price", None
    price = prices.get(ladder["Stock"])
    if price is None:
        log.warning("no price for %s", ladder["Stock"])
        return "no price", None
    log.debug("%s %s", ladder["Stock"], price)

    level = passed_level(ladder, price)
    if level is None:
        return "waiting", price
    following = next_level(dict(ladder, Last=level))
    upcoming = (
        f"next {following:g}"
        if following > 0
        else "the last level"
    )
    text = (
        f"{ladder['Stock']} {ladder['Direction']} to "
        f"{price:.2f}, passed {level:g} "
        f"(ladder {ladder['Id']}, {upcoming})"
    )
    try:
        notify(text)
    except Exception as e:
        # the level isn't saved, so it is sent again at
        # the next check
        log.warning("could not send %r: %s", text, e)
        return "no notify", price
    ladder_set_last(ladder["Id"], level)
    ladder["Last"] = level
    log.info("sent: %s", text)
    return "waiting", price


def _status(ladder_id, pid, started, state, price=None):
    """write the heartbeat that 'ls tasks' shows"""
    previous = ladder_status_get(ladder_id) or {}
    try:
        ladder_status_set(
            ladder_id,
            {
                "pid": pid,
                "started": started
                or previous.get("started"),
                "updated": _now(),
                "state": state,
                "price": price,
            },
        )
    except Exception:
        log.exception("could not write the ladder status")


def _stop_on_signal(signum, frame):
    # handled like Ctrl+C: the heartbeat says 'stopped'
    raise KeyboardInterrupt


if __name__ == "__main__" and len(sys.argv) == 2:
    run(int(sys.argv[1]))

elif __name__ == "__main__":
    import unittest

    def ladder(direction, step, last):
        return {
            "Id": 1,
            "Stock": "SOXL",
            "Direction": direction,
            "Step": step,
            "From": last,
            "Last": last,
        }

    class LevelsTest(unittest.TestCase):
        def test_next_level(self):
            self.assertEqual(
                next_level(ladder("down", 10, 100)), 90
            )
            self.assertEqual(
                next_level(ladder("up", 2.5, 80)), 82.5
            )

        def test_down_not_reached(self):
            down = ladder("down", 10, 100)
            self.assertIsNone(passed_level(down, 95))
            self.assertIsNone(passed_level(down, 90.01))
            self.assertIsNone(passed_level(down, 120))

        def test_down_passed(self):
            down = ladder("down", 10, 100)
            self.assertEqual(passed_level(down, 90), 90)
            self.assertEqual(passed_level(down, 85), 90)
            # several levels at once: the farthest
            self.assertEqual(passed_level(down, 71), 80)
            self.assertEqual(passed_level(down, 70), 70)

        def test_up_passed(self):
            up = ladder("up", 10, 100)
            self.assertIsNone(passed_level(up, 109.99))
            self.assertEqual(passed_level(up, 110), 110)
            self.assertEqual(passed_level(up, 131), 130)
            self.assertIsNone(passed_level(up, 80))

        def test_float_steps(self):
            up = ladder("up", 0.1, 0.3)
            self.assertEqual(passed_level(up, 0.4), 0.4)
            down = ladder("down", 0.1, 0.3)
            self.assertEqual(passed_level(down, 0.1), 0.1)

        def test_create_checks(self):
            for args in (
                ("SOXL", "left", 10, 100),
                ("SOXL", "down", 0, 100),
                ("SOXL", "up", 10, -1),
                ("SOXL", "down", 100, 100),
            ):
                with self.assertRaises(LadderError):
                    create(*args)

    unittest.main()

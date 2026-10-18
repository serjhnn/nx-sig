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
#   process_runs(pid, script, arg=None)
#       True if pid is a live process running script
#   release_if_idle(ending_id=None, watcher_ending=False,
#                   alerts_ending=False)
#       release the wake lock and the background tasks
#       when none runs any more
#   spawn(args, out_path), wake_lock(command),
#   last_line(paths), setup_logging(path),
#   interval(key)
#       the process helpers, also of alerts.py
#   run(ladder_id)
#       the process: check the price and notify

import glob
import logging
import logging.handlers
import math
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime

import requests

import storage
import tasks_owner
from storage import (
    ROOT_DIR,
    alerts_status_get,
    ladder_add,
    ladder_delete,
    ladder_get,
    ladder_set_last,
    ladder_status_get,
    ladder_status_set,
    ladders_get_all,
    mtsig_pid_get,
)
from trade_engine import config, get_latest_prices
from telegram_notify import notify

SCRIPT = os.path.join(ROOT_DIR, "scripts", "ladder.py")
DIRECTIONS = ("down", "up")
DEFAULT_INTERVAL = 30


def interval(key):
    """config "timing" key, in seconds"""
    timing = config.get("timing")
    if not isinstance(timing, dict):
        timing = {}
    return timing.get(key, DEFAULT_INTERVAL)


INTERVAL = interval("ladder_interval")
# 'ls tasks' shows a ladder as 'no reply' when its
# heartbeat is older than this
STALE_SECONDS = max(3 * INTERVAL, 120)
# how long start() watches for a crash at start
START_CHECK_SECONDS = 2
STOP_WAIT_SECONDS = 10
LOG_MAX_BYTES = 200_000
LOG_BACKUP_COUNT = 2
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
    if pid and process_runs(pid, "ladder.py", ladder_id):
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
    process = spawn(
        [SCRIPT, str(ladder_id)], _out_path(ladder_id)
    )
    # so running_pid() knows it before the process writes
    # its first heartbeat
    ladder_status_set(
        ladder_id,
        {
            "pid": process.pid,
            "started": _now(),
            "updated": _now(),
            "state": "starting",
        },
    )
    # catch a crash at start, e.g. a missing package
    deadline = time.monotonic() + START_CHECK_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            release_if_idle()
            raise LadderError(
                f"ladder {ladder_id} stopped right after "
                "starting: "
                + last_line(
                    [
                        _out_path(ladder_id),
                        _log_path(ladder_id),
                    ]
                )
            )
        time.sleep(0.2)
    return process.pid


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
    deadline = time.monotonic() + STOP_WAIT_SECONDS
    while time.monotonic() < deadline:
        _reap(pid)
        if not running_pid(ladder_id):
            break
        time.sleep(0.2)
    else:
        os.kill(pid, signal.SIGKILL)
        _status(ladder_id, pid, None, "stopped")
    release_if_idle()
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


def _reap(pid):
    # a process started by this shell stays a zombie
    # until it is waited for
    try:
        os.waitpid(pid, os.WNOHANG)
    except (ChildProcessError, OSError):
        pass


def process_runs(pid, script, arg=None):
    """
    True if pid is alive and runs script (with arg as
    its last argument), so a pid that Android gave to
    another program isn't taken for it
    """
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            args = f.read().decode(errors="replace")
    except OSError:
        if os.name == "nt":
            return False
        # no /proc: only check that it is alive
        try:
            os.kill(pid, 0)
        except PermissionError:
            return True
        except OSError:
            return False
        return True
    # a zombie (ended, not yet reaped) has no args
    args = args.split("\0")[:-1]
    if not any(a.endswith(script) for a in args):
        return False
    return arg is None or args[-1] == str(arg)


def spawn(args, out_path):
    """start python <args> as a background process
    with its output in out_path, holding the Termux wake
    lock; return the Popen"""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    wake_lock("termux-wake-lock")
    with open(out_path, "w") as out:
        return subprocess.Popen(
            [sys.executable, *args],
            cwd=ROOT_DIR,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            env={**os.environ, "LOG_CONSOLE": "0"},
            # its own session, so Ctrl+C or closing the
            # shell doesn't reach it
            start_new_session=True,
        )


def wake_lock(command):
    # Termux only: keeps Android from pausing the process
    if shutil.which(command):
        subprocess.run([command], check=False)


def release_if_idle(
    ending_id=None,
    watcher_ending=False,
    alerts_ending=False,
):
    """release the Termux wake lock and the background
    tasks (tasks_owner.release) when no ladder but
    ending_id, no mail broker and no alerts process
    (unless it is the one ending) runs any more"""
    others = [
        l["Id"]
        for l in ladders_get_all()
        if l["Id"] != ending_id
    ]
    if any(running_pid(i) for i in others):
        return
    pid = mtsig_pid_get()
    if (
        not watcher_ending
        and pid
        and process_runs(pid, "order_watcher.py")
    ):
        return
    alerts = (alerts_status_get() or {}).get("pid")
    if (
        not alerts_ending
        and alerts
        and process_runs(alerts, "alerts.py", "run")
    ):
        return
    wake_lock("termux-wake-unlock")
    tasks_owner.release()


def last_line(paths):
    """the last line of the first of paths (a process
    output, its log) that has one"""
    for path in paths:
        try:
            with open(path) as f:
                lines = [l for l in f if l.strip()]
        except OSError:
            continue
        if lines:
            return lines[-1].strip()
    return "no output, see the log"


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
    setup_logging(_log_path(ladder_id))
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
        release_if_idle(ending_id=ladder_id)


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


def setup_logging(path):
    """log to path ({storage_dir}/logs/...) and to the
    console unless LOG_CONSOLE=0"""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    handlers = [
        logging.handlers.RotatingFileHandler(
            path,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    ]
    if os.getenv("LOG_CONSOLE", "1") != "0":
        handlers.append(logging.StreamHandler())
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )
    root = logging.getLogger()
    root.setLevel(level)
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)


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

        def test_process_runs(self):
            self.assertTrue(
                process_runs(os.getpid(), "ladder.py")
            )
            self.assertFalse(
                process_runs(os.getpid(), "other.py")
            )

    unittest.main()

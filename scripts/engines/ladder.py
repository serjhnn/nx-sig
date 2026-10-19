# ladder: the ladders engine, price-step alerts for one
# stock; every ladder runs as its own process,
# services/ladder_service.py
#
#   python tests/test_ladder.py     the tests
#
# a ladder sends a message (notifier.py: Telegram or a
# Termux notification) each time the price passes its
# next level: 'SOXL down 10 from 100' at 90, 80, 70,
# ... When the price jumps over several levels between
# two checks, one message names the farthest.
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
#   get(ladder_id), get_all(), status(ladder_id)
#       the saved ladders and the heartbeat of one
#   next_level(ladder), passed_level(ladder, price)
#       the level math
#   save_status(ladder_id, pid, started, state,
#               price=None)
#       write the heartbeat that 'ls tasks' shows
#   log_path(ladder_id)
#       the log file of its process
#
# the process helpers (spawn, release_if_idle, ...) are
# in process.py

import glob
import logging
import math
import os
import signal
import time
from datetime import datetime

import config
import process
import storage
import tasks_owner
from storage import (  # noqa: F401, Stock for the shell
    ROOT_DIR,
    Stock,
    ladder_add,
    ladder_delete,
    ladder_get,
    ladder_set_last,
    ladder_status_get,
    ladder_status_set,
    ladders_get_all,
)

SERVICE = "ladder_service.py"
SCRIPT = os.path.join(
    ROOT_DIR, "scripts", "services", SERVICE
)
DIRECTIONS = ("down", "up")
INTERVAL = config.interval("ladder_interval")
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
        pid, SERVICE, ladder_id
    ):
        return pid
    return None


def get(ladder_id):
    return ladder_get(ladder_id)


def get_all():
    return ladders_get_all()


def status(ladder_id):
    """the heartbeat of the ladder's process, or None"""
    return ladder_status_get(ladder_id)


def set_last(ladder_id, level):
    """save the last level the ladder notified"""
    ladder_set_last(ladder_id, level)


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
                        log_path(ladder_id),
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
    if not process.kill(pid, signal.SIGTERM):
        process.release_if_idle()
        return False
    deadline = time.monotonic() + process.STOP_WAIT_SECONDS
    while time.monotonic() < deadline:
        process.reap(pid)
        if not running_pid(ladder_id):
            break
        time.sleep(0.2)
    else:
        process.kill(pid, signal.SIGKILL)
        save_status(ladder_id, pid, None, "stopped")
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


def log_path(ladder_id):
    return os.path.join(
        storage.DB_DIR, "logs", f"ladder_{ladder_id}.log"
    )


def _now():
    return datetime.now().isoformat(timespec="seconds")


def save_status(ladder_id, pid, started, state, price=None):
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

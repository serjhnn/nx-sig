# mail_broker: the mail broker engine, starts and stops
# scripts/mtsig/order_watcher.py, which records broker
# order emails as trades
#
#   python tests/test_mail_broker.py   the tests
#
# order_watcher.py needs Python 3.14 (IMAP IDLE): the
# shell's own Python when it is new enough, else
# WATCHER_PYTHON or the first of python3.14, python3,
# python that is. it runs only on the device that runs
# the background tasks (tasks_owner.py), never in the
# demo: it would record real emails into the demo data.
# heartbeat: mtsig_status.json, written by the watcher
# with its pid; logs: {storage_dir}/logs/mtsig.log
#
# public functions:
#   start(force=False), stop(), running_pid()
#       the process, TASK (a process.BackgroundTask);
#       force takes the background tasks over
#   status()
#       its heartbeat, or None
#   save_status(pid, started, state)
#       write the heartbeat, keeping the last order
#       and error
#   find_python()
#       the Python for it, None for this one
#   log_path()
#       the log file of the process
#   log_tail(count=5)
#       its last lines, for 'ls mail-broker'
#   summary()
#       its state for 'status' and the web page
#   task()
#       its task row, None if it isn't running
#
# a task row (the 'ls tasks' row, the web's task
# list) is {"id", "task", "pid", "started", "state",
# "healthy"}, started a datetime or None

import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime

import config
import process
import storage

SERVICE = "order_watcher.py"
SCRIPT = os.path.join(
    config.ROOT_DIR, "scripts", "mtsig", SERVICE
)
NEEDS = (3, 14)
_NEEDS_CHECK = (
    "import sys; sys.exit(sys.version_info < " f"{NEEDS!r})"
)
# the IMAP login takes a moment, and the logout at
# stop up to 20s
START_CHECK_SECONDS = 3
# order_watcher.py writes a heartbeat at least every 9
# minutes (IMAP IDLE renewal)
STALE_SECONDS = 15 * 60
# an order it could not record stays in 'status' this
# long
ERROR_DAYS = 7
STOP_WAIT_SECONDS = 20

log = logging.getLogger("mail_broker")


class MailBrokerError(Exception):
    """the mail broker can't start; the text says
    why"""


def status():
    return storage.watcher_status_get()


def running_pid():
    return TASK.running_pid()


def start(force=False):
    """
    start the mail broker and return its pid; raise
    MailBrokerError in the demo, without Python 3.14,
    when it already runs, another device runs the
    background tasks (unless force) or it stops right
    away (e.g. a wrong password)
    """
    return TASK.start(force=force)


def stop():
    """stop the mail broker (SIGTERM: a clean logout,
    SIGKILL after 20s), True if it was running"""
    return TASK.stop()


def save_status(pid, started, state):
    """write the heartbeat; started None keeps the
    saved one, the last order and error are kept"""
    previous = status() or {}
    try:
        storage.watcher_status_set(
            {
                **previous,
                "pid": pid,
                "started": started
                or previous.get("started"),
                "updated": _now(),
                "state": state,
            }
        )
    except Exception:
        log.exception("could not write the status")


def find_python():
    """
    the Python for order_watcher.py: None when this
    one is new enough, else the path of WATCHER_PYTHON
    or of the first of python3.14, python3, python that
    is; raise MailBrokerError if none is
    """
    if sys.version_info >= NEEDS:
        return None
    names = [
        os.getenv("WATCHER_PYTHON"),
        "python3.14",
        "python3",
        "python",
    ]
    for name in filter(None, names):
        path = shutil.which(name)
        if path and _new_enough(path):
            return path
    raise MailBrokerError(
        "the mail broker needs Python 3.14 or newer, "
        "set WATCHER_PYTHON=/path/to/python3.14"
    )


def log_path():
    return os.path.join(storage.DB_DIR, "logs", "mtsig.log")


def log_tail(count=5):
    """the last count lines of its log (not the
    rotated ones), [] if there is none"""
    return process.log_tail(log_path(), count)


def summary():
    """its state for 'status' and the web page:
    {"state", "updated", "last_order", "error", "log"}

    state is "demo" (it never runs in the demo), "not
    started", "unknown" (a bad heartbeat), "stopped",
    "no reply" (no heartbeat for STALE_SECONDS),
    "running" or the heartbeat's own (e.g.
    "crashed"); updated the heartbeat's datetime;
    error {"time", "text"} of an order it could not
    record in the last ERROR_DAYS; log its log file
    when it is worth a look (an error, a crash, no
    reply); each None when there is none"""
    result = {
        "state": "demo",
        "updated": None,
        "last_order": None,
        "error": None,
        "log": None,
    }
    if config.demo():
        return result
    heartbeat = status()
    if not heartbeat or not heartbeat.get("updated"):
        result["state"] = "not started"
        return result
    try:
        updated = datetime.fromisoformat(
            heartbeat["updated"]
        )
    except ValueError:
        result["state"] = "unknown"
        return result

    raw = heartbeat.get("state", "")
    age = (datetime.now() - updated).total_seconds()
    if raw == "stopped":
        state = "stopped"
    elif age > STALE_SECONDS:
        state = "no reply"
    elif raw in ("starting", "connected", "waiting"):
        state = "running"
    else:
        state = raw
    result.update(
        state=state,
        updated=updated,
        last_order=heartbeat.get("last_order") or None,
    )
    error = _recent_error(heartbeat)
    result["error"] = error
    if heartbeat.get("log") and (
        error
        or raw.startswith("crashed")
        or age > STALE_SECONDS
    ):
        result["log"] = heartbeat["log"]
    return result


def _recent_error(heartbeat):
    """{"time", "text"} of its last error if it is
    newer than ERROR_DAYS, else None"""
    error = heartbeat.get("last_error") or {}
    try:
        time = (
            datetime.fromisoformat(error["time"])
            if error.get("time")
            else None
        )
    except ValueError:
        time = None
    if not time:
        return None
    if (datetime.now() - time).days >= ERROR_DAYS:
        return None
    return {"time": time, "text": error.get("text", "")}


def task():
    """the task row of the mail broker, None if it
    isn't running"""
    pid = running_pid()
    if pid is None:
        return None
    heartbeat = status() or {}
    started = updated = None
    try:
        started = datetime.fromisoformat(
            heartbeat["started"]
        )
        updated = datetime.fromisoformat(
            heartbeat["updated"]
        )
    except (KeyError, TypeError, ValueError):
        pass
    state = heartbeat.get("state", "") if updated else "-"
    healthy = state in ("starting", "connected", "waiting")
    if updated:
        age = (datetime.now() - updated).total_seconds()
        if age > STALE_SECONDS:
            state, healthy = "no reply", False
    return {
        "id": "-",
        "task": "mail-broker",
        "pid": pid,
        "started": started,
        "state": state,
        "healthy": healthy,
    }


def _new_enough(path):
    try:
        result = subprocess.run(
            [path, "-c", _NEEDS_CHECK],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _out_path():
    # errors before its logging is set up, e.g. a
    # missing package
    return os.path.join(storage.DB_DIR, "logs", "mtsig.out")


def _now():
    return datetime.now().isoformat(timespec="seconds")


class _MailBrokerTask(process.BackgroundTask):
    service = SERVICE
    script = SCRIPT
    name = "the mail broker"
    error = MailBrokerError
    start_check = START_CHECK_SECONDS
    stop_wait = STOP_WAIT_SECONDS
    # found by check_start()
    _python = None

    def check_start(self, key):
        if config.demo():
            raise MailBrokerError(
                "the mail broker is not in the demo"
            )
        self._python = find_python()

    def python(self):
        return self._python

    def arg(self, key):
        # it takes no argument
        return None

    def args(self, key):
        return [self.script]

    def status_get(self, key):
        return status()

    def save_status(self, key, pid, started, state):
        save_status(pid, started, state)

    def out_path(self, key):
        return _out_path()

    def log_path(self, key):
        return log_path()


TASK = _MailBrokerTask()

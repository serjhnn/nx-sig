# web: the web server engine, a small page with the
# nX-sig logo, served by one background process,
# services/web_service.py
#
#   python tests/test_web.py     the tests
#
# it listens on config "web" "host" and "port"
# (127.0.0.1:8080 by default, so only this device can
# open it). 'ls tasks' shows it, but it sends nothing,
# so it isn't tied to the device that runs the
# background tasks (tasks_owner.py): it runs on any
# device, without the Termux wake lock, and
# web_status.json is not synced.
# logs: {storage_dir}/logs/web.log
#
# public functions:
#   url()
#       the address to open in a browser
#   start(), stop(), running_pid()
#       the process, TASK (a process.BackgroundTask)
#   status()
#       its heartbeat, or None
#   save_status(pid, started, state)
#       write the heartbeat
#   log_path()
#       the log file of the process

import logging
import os
from datetime import datetime

import config
import process
import storage

SERVICE = "web_service.py"
SCRIPT = os.path.join(
    config.ROOT_DIR, "scripts", "services", SERVICE
)

log = logging.getLogger("web")


class WebError(Exception):
    pass


def url():
    host = config.web_host()
    if host == "0.0.0.0":
        host = "127.0.0.1"
    return f"http://{host}:{config.web_port()}/"


def status():
    return storage.web_status_get()


def running_pid():
    return TASK.running_pid()


def start():
    """
    start the web server and return its pid; raise
    WebError if it already runs or stops right away
    (the port is taken)
    """
    return TASK.start()


def stop():
    """stop the web server (SIGTERM, then SIGKILL),
    True if it was running"""
    return TASK.stop()


def save_status(pid, started, state):
    """write the heartbeat; started None keeps the
    saved one"""
    previous = status() or {}
    try:
        storage.web_status_set(
            {
                "pid": pid,
                "started": started
                or previous.get("started"),
                "updated": _now(),
                "state": state,
                "url": url(),
            }
        )
    except Exception:
        log.exception("could not write the status")


def _out_path():
    return os.path.join(storage.DB_DIR, "logs", "web.out")


def log_path():
    return os.path.join(storage.DB_DIR, "logs", "web.log")


def _now():
    return datetime.now().isoformat(timespec="seconds")


class _WebTask(process.BackgroundTask):
    # sends nothing: on any device, no wake lock
    service = SERVICE
    script = SCRIPT
    name = "the web server"
    owner_bound = False
    wake = False
    error = WebError

    def status_get(self, key):
        return status()

    def save_status(self, key, pid, started, state):
        save_status(pid, started, state)

    def out_path(self, key):
        return _out_path()

    def log_path(self, key):
        return log_path()


TASK = _WebTask()

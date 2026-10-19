# process: the helpers of the background processes
# (the ladders, the alerts, the mail broker)
#
#   python tests/test_process.py  the tests
#
# public functions:
#   spawn(args, out_path)
#       start python <args> in the background, holding
#       the Termux wake lock; return the Popen
#   process_runs(pid, script, arg=None)
#       True if pid is a live process running script
#   reap(pid)
#       wait for an ended child, so it isn't a zombie
#   release_if_idle(ending_id=None, watcher_ending=False,
#                   alerts_ending=False)
#       release the wake lock and the background tasks
#       when none runs any more
#   wake_lock(command)
#       termux-wake-lock / termux-wake-unlock
#   last_line(paths)
#       the last line of a process output or its log
#   setup_logging(path)
#       log to path and to the console

import logging
import logging.handlers
import os
import shutil
import subprocess
import sys

import tasks_owner
from storage import (
    ROOT_DIR,
    alerts_status_get,
    ladder_status_get,
    ladders_get_all,
    mtsig_pid_get,
)

# how long start() watches for a crash at start
START_CHECK_SECONDS = 2
# how long stop() waits for SIGTERM before SIGKILL
STOP_WAIT_SECONDS = 10
LOG_MAX_BYTES = 200_000
LOG_BACKUP_COUNT = 2


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


def reap(pid):
    # a process started by this shell stays a zombie
    # until it is waited for
    try:
        os.waitpid(pid, os.WNOHANG)
    except (ChildProcessError, OSError):
        pass


def release_if_idle(
    ending_id=None,
    watcher_ending=False,
    alerts_ending=False,
):
    """release the Termux wake lock and the background
    tasks (tasks_owner.release) when no ladder but
    ending_id, no mail broker and no alerts process
    (unless it is the one ending) runs any more"""
    for l in ladders_get_all():
        if l["Id"] == ending_id:
            continue
        pid = (ladder_status_get(l["Id"]) or {}).get("pid")
        if pid and process_runs(
            pid, "ladder_service.py", l["Id"]
        ):
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


def wake_lock(command):
    # Termux only: keeps Android from pausing the process
    if shutil.which(command):
        subprocess.run([command], check=False)


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

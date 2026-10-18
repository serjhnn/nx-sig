# process: the helpers of the background processes
# (the ladders, the alerts, the mail broker)
#
#   python scripts/process.py   run the tests
#
# public functions:
#   interval(key)
#       config "timing" key, in seconds (default
#       DEFAULT_INTERVAL)
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
    config,
    ladder_status_get,
    ladders_get_all,
    mtsig_pid_get,
)

DEFAULT_INTERVAL = 30
# how long start() watches for a crash at start
START_CHECK_SECONDS = 2
# how long stop() waits for SIGTERM before SIGKILL
STOP_WAIT_SECONDS = 10
LOG_MAX_BYTES = 200_000
LOG_BACKUP_COUNT = 2


def interval(key):
    """config "timing" key, in seconds"""
    timing = config.get("timing")
    if not isinstance(timing, dict):
        timing = {}
    return timing.get(key, DEFAULT_INTERVAL)


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
        if pid and process_runs(pid, "ladder.py", l["Id"]):
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


if __name__ == "__main__":
    import unittest
    from unittest import mock

    class ProcessTest(unittest.TestCase):
        def test_process_runs(self):
            pid = os.getpid()
            self.assertTrue(process_runs(pid, "process.py"))
            self.assertFalse(process_runs(pid, "other.py"))

        def test_interval(self):
            for timing in ({}, None, [30], {"other": 5}):
                with mock.patch.dict(
                    config, {"timing": timing}
                ):
                    self.assertEqual(
                        interval("ladder_interval"),
                        DEFAULT_INTERVAL,
                    )
            with mock.patch.dict(
                config, {"timing": {"alert_interval": 5}}
            ):
                self.assertEqual(
                    interval("alert_interval"), 5
                )
            with mock.patch.dict(config):
                config.pop("timing", None)
                self.assertEqual(
                    interval("ladder_interval"),
                    DEFAULT_INTERVAL,
                )

        def test_last_line(self):
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                empty = os.path.join(tmp, "a.out")
                log = os.path.join(tmp, "a.log")
                open(empty, "w").close()
                with open(log, "w") as f:
                    f.write("one\ntwo\n\n")
                missing = os.path.join(tmp, "none")
                self.assertEqual(
                    last_line([missing, empty, log]), "two"
                )
                self.assertEqual(
                    last_line([empty]),
                    "no output, see the log",
                )

    unittest.main()

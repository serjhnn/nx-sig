# process: the helpers of the background processes
# (the ladders, the alerts, the mail broker)
#
#   python tests/test_process.py  the tests
#
# public functions:
#   BackgroundTask
#       the base class of a background task: an engine
#       subclass says its script, heartbeat and paths,
#       running_pid(), start() and stop() are shared
#   spawn(args, out_path, wake=True, python=None)
#       start python <args> in the background, holding
#       the Termux wake lock (unless not wake); return
#       the Popen
#   process_runs(pid, script, arg=None)
#       True if pid is a live process running script
#   kill(pid, sig)
#       send sig to pid, False if it is gone or not
#       ours
#   reap(pid)
#       wait for an ended child, so it isn't a zombie
#   tasks()
#       every kind of task, the TASK of each engine
#   tasks_run(ending=None)
#       True if an owner-bound task (a ladder, the
#       alerts, the mail broker) runs, but ending, the
#       (task, key) that ends
#   release_if_idle(ending=None)
#       release the wake lock and the background tasks
#       when none runs any more
#   wake_lock(command)
#       termux-wake-lock / termux-wake-unlock
#   last_line(paths)
#       the last line of a process output or its log
#   setup_logging(path)
#       log to path and to the console

import importlib
import logging
import logging.handlers
import os
import pkgutil
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime

import tasks_owner
from storage import ROOT_DIR

# how long start() watches for a crash at start
START_CHECK_SECONDS = 2
# how long stop() waits for SIGTERM before SIGKILL
STOP_WAIT_SECONDS = 10
LOG_MAX_BYTES = 200_000
LOG_BACKUP_COUNT = 2


class BackgroundTask:
    """
    a kind of background task, one process per key
    (a ladder's id; None for a task that runs once,
    like the alerts). a subclass sets the attributes
    and implements status_get(), save_status(),
    out_path() and log_path(); the others have
    defaults
    """

    # the script the process runs, e.g.
    # "alert_service.py", and its full path
    service = ""
    script = ""
    # "the alerts process": how the messages name it
    name = ""
    # claims the background tasks for this device
    # (tasks_owner.py) and releases them when the
    # last one stops
    owner_bound = True
    # holds the Termux wake lock
    wake = True
    # seconds to watch for a crash at start, to wait
    # after SIGTERM; None: the constants above
    start_check = None
    stop_wait = None
    # the exception start() raises
    error = Exception

    def status_get(self, key):
        """its heartbeat, a dict with "pid", or None"""
        raise NotImplementedError

    def save_status(self, key, pid, started, state):
        """write its heartbeat; started None keeps the
        saved one"""
        raise NotImplementedError

    def out_path(self, key):
        """the process output (errors before its
        logging is set up)"""
        raise NotImplementedError

    def log_path(self, key):
        raise NotImplementedError

    def keys(self):
        """the keys of its saved tasks, which may run:
        the ladders' ids, [None] for one process"""
        return [None]

    def label(self, key):
        """the task in a message: 'ladder 3'"""
        return self.name

    def arg(self, key):
        """the last argument of the script, which
        running_pid() checks"""
        return "run" if key is None else key

    def args(self, key):
        """the script and its arguments"""
        return [self.script, str(self.arg(key))]

    def python(self):
        """the interpreter, None for this one"""
        return None

    def check_start(self, key):
        """raise self.error if it can't start"""

    def already_running(self, key, pid):
        """the message when it runs already"""
        return f"{self.label(key)} already runs (pid {pid})"

    def starting(self, key, pid):
        """the first heartbeat, written by start(), so
        running_pid() knows the process before it
        writes its own"""
        self.save_status(key, pid, _now(), "starting")

    def running_pid(self, key=None):
        """the pid of its process, None if it doesn't
        run"""
        pid = (self.status_get(key) or {}).get("pid")
        if pid and process_runs(
            pid, self.service, self.arg(key)
        ):
            return pid
        return None

    def start(self, key=None, force=False):
        """
        start its process and return the pid; raise
        self.error if check_start() refuses, it runs
        already, another device runs the background
        tasks (owner_bound, unless force) or it stops
        right away
        """
        self.check_start(key)
        pid = self.running_pid(key)
        if pid:
            raise self.error(self.already_running(key, pid))
        if self.owner_bound:
            try:
                tasks_owner.claim(force)
            except tasks_owner.OwnerError as e:
                raise self.error(str(e)) from None
        out = self.out_path(key)
        child = spawn(
            self.args(key),
            out,
            wake=self.wake,
            python=self.python(),
        )
        self.starting(key, child.pid)
        # catch a crash at start, e.g. a missing package
        deadline = time.monotonic() + _or(
            self.start_check, START_CHECK_SECONDS
        )
        while time.monotonic() < deadline:
            if child.poll() is not None:
                self._release()
                raise self.error(
                    f"{self.label(key)} stopped right "
                    "after starting: "
                    + last_line([out, self.log_path(key)])
                )
            time.sleep(0.2)
        return child.pid

    def stop(self, key=None):
        """
        stop its process (SIGTERM, then SIGKILL after
        stop_wait), True if it was running
        """
        pid = self.running_pid(key)
        if not pid:
            return False
        if not kill(pid, signal.SIGTERM):
            self._release()
            return False
        deadline = time.monotonic() + _or(
            self.stop_wait, STOP_WAIT_SECONDS
        )
        while time.monotonic() < deadline:
            reap(pid)
            if not self.running_pid(key):
                break
            time.sleep(0.2)
        else:
            kill(pid, signal.SIGKILL)
            self.save_status(key, pid, None, "stopped")
        self._release()
        return True

    def _release(self):
        if self.owner_bound:
            release_if_idle()


def spawn(args, out_path, wake=True, python=None):
    """start python <args> (python is the path of the
    interpreter, this one if None) as a background
    process with its output in out_path, holding the
    Termux wake lock unless not wake; return the
    Popen"""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    if wake:
        wake_lock("termux-wake-lock")
    with open(out_path, "w") as out:
        return subprocess.Popen(
            [python or sys.executable, *args],
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
        # no /proc (or Android hides another app's):
        # only check that it is alive and ours, a
        # process of another user (PermissionError) is
        # never one of the tasks
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    # a zombie (ended, not yet reaped) has no args
    args = args.split("\0")[:-1]
    if not any(a.endswith(script) for a in args):
        return False
    return arg is None or args[-1] == str(arg)


def kill(pid, sig):
    """send sig to pid; False if it ended already or
    belongs to another user, so it isn't ours"""
    try:
        os.kill(pid, sig)
    except OSError:
        return False
    return True


def reap(pid):
    # a process started by this shell stays a zombie
    # until it is waited for
    try:
        os.waitpid(pid, os.WNOHANG)
    except (ChildProcessError, OSError):
        pass


def tasks():
    """every kind of background task: the TASK of each
    engines/*.py that has one, so a new engine with a
    TASK is found without being named here"""
    # engines import this module: import them only now
    import engines

    found = []
    for info in pkgutil.iter_modules(engines.__path__):
        module = importlib.import_module(
            f"engines.{info.name}"
        )
        task = getattr(module, "TASK", None)
        if isinstance(task, BackgroundTask):
            found.append(task)
    return found


def tasks_run(ending=None):
    """True if an owner-bound task runs (a ladder, the
    alerts, the mail broker), except ending, the
    (task, key) that is ending"""
    for task in tasks():
        if not task.owner_bound:
            continue
        for key in task.keys():
            if ending == (task, key):
                continue
            if task.running_pid(key):
                return True
    return False


def release_if_idle(ending=None):
    """release the Termux wake lock and the background
    tasks (tasks_owner.release) when no task runs any
    more (tasks_run(ending))"""
    if tasks_run(ending):
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


def _or(value, default):
    # 0 is a value, not a missing one
    return default if value is None else value


def _now():
    return datetime.now().isoformat(timespec="seconds")

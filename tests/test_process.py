# tests of scripts/process.py
#
#   python tests/test_process.py

import os
import signal
import subprocess
import sys
import tempfile

import unittest

import paths  # noqa: F401, scripts/ on sys.path
from unittest import mock

import process
from process import (
    BackgroundTask,
    kill,
    last_line,
    process_runs,
)


class ProcessTest(unittest.TestCase):
    def test_process_runs(self):
        # a child that runs a script, as the tasks do
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, "task.py")
            with open(script, "w") as f:
                f.write(
                    "import time\n"
                    "print('up', flush=True)\n"
                    "time.sleep(30)\n"
                )
            child = subprocess.Popen(
                [sys.executable, script, "7"],
                stdout=subprocess.PIPE,
            )
            try:
                # until it prints, the child may not run
                # the script yet (fork before exec)
                child.stdout.readline()
                pid = child.pid
                self.assertTrue(
                    process_runs(pid, "task.py")
                )
                self.assertTrue(
                    process_runs(pid, "task.py", 7)
                )
                self.assertFalse(
                    process_runs(pid, "task.py", 8)
                )
                self.assertFalse(
                    process_runs(pid, "other.py")
                )
            finally:
                child.kill()
                child.wait()
                child.stdout.close()

    def test_other_users_process(self):
        # Android hides another app's /proc/<pid>, and
        # its pid can't be signaled: not one of the tasks
        denied = mock.patch(
            "os.kill", side_effect=PermissionError
        )
        hidden = mock.patch(
            "builtins.open", side_effect=PermissionError
        )
        with denied, hidden:
            self.assertFalse(process_runs(1, "alerts.py"))
        with denied:
            self.assertFalse(kill(1, 15))

    def test_kill_ended(self):
        child = subprocess.Popen([sys.executable, "-c", ""])
        child.wait()
        self.assertFalse(kill(child.pid, 15))

    def test_last_line(self):
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


class TasksTest(unittest.TestCase):
    def test_tasks(self):
        # the TASK of every engine that has one
        from engines import (
            alerts,
            demo_prices,
            ladder,
            mail_broker,
            web,
        )

        found = process.tasks()
        for task in (
            alerts.TASK,
            demo_prices.TASK,
            ladder.TASK,
            mail_broker.TASK,
            web.TASK,
        ):
            self.assertIn(task, found)
        self.assertEqual(len(found), 5)

    def test_tasks_run(self):
        # owner-bound tasks only, but the ending one
        bound = FakeTask.__new__(FakeTask)
        bound.keys = lambda: [1, 2]
        running = {(bound, 2)}
        bound.running_pid = lambda key: (
            (bound, key) in running and 9
        )
        free = FakeTask.__new__(FakeTask)
        free.owner_bound = False
        free.running_pid = lambda key: 9
        with mock.patch.object(
            process, "tasks", lambda: [free, bound]
        ):
            self.assertTrue(process.tasks_run())
            self.assertTrue(
                process.tasks_run(ending=(bound, 1))
            )
            self.assertFalse(
                process.tasks_run(ending=(bound, 2))
            )
            running.clear()
            self.assertFalse(process.tasks_run())


# the service of FakeTask: prints, then sleeps; argv
# "crash" ends right away, "stubborn" ignores SIGTERM
FAKE_SERVICE = """\
import signal, sys, time
print("up", flush=True)
if sys.argv[-1] == "crash":
    sys.exit("boom")
if sys.argv[-1] == "stubborn":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
time.sleep(30)
"""


class FakeError(Exception):
    pass


class FakeTask(BackgroundTask):
    service = "fake_service.py"
    name = "the fake"
    wake = False
    start_check = 0.3
    stop_wait = 0.3
    error = FakeError

    def __init__(self, folder):
        self.folder = folder
        self.script = os.path.join(folder, self.service)
        with open(self.script, "w") as f:
            f.write(FAKE_SERVICE)
        self.status = {}

    def status_get(self, key):
        return self.status.get(key)

    def save_status(self, key, pid, started, state):
        previous = self.status.get(key) or {}
        self.status[key] = {
            "pid": pid,
            "started": started or previous.get("started"),
            "state": state,
        }

    def out_path(self, key):
        return os.path.join(self.folder, f"{key}.out")

    def log_path(self, key):
        return os.path.join(self.folder, f"{key}.log")


class BackgroundTaskTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.task = FakeTask(tmp.name)
        self.claims = []
        self.releases = []
        patcher = mock.patch.object(
            process.tasks_owner, "claim", self.claims.append
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(
            process,
            "release_if_idle",
            lambda: self.releases.append(1),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        # no Termux here, but never take the wake lock
        patcher = mock.patch.object(
            process, "wake_lock", lambda command: None
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        # keep the children, so the test ends them
        self.children = []
        spawn = process.spawn

        def keep(*args, **kwargs):
            child = spawn(*args, **kwargs)
            self.children.append(child)
            return child

        patcher = mock.patch.object(process, "spawn", keep)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._end_children)

    def _end_children(self):
        for child in self.children:
            if child.poll() is None:
                child.send_signal(signal.SIGKILL)
            child.wait()

    def test_start_and_stop(self):
        pid = self.task.start()
        self.assertEqual(self.task.running_pid(), pid)
        self.assertEqual(
            self.task.status[None]["state"], "starting"
        )
        # owner_bound: claimed, not forced
        self.assertEqual(self.claims, [False])
        with self.assertRaises(FakeError) as e:
            self.task.start()
        self.assertEqual(
            str(e.exception),
            f"the fake already runs (pid {pid})",
        )
        self.assertTrue(self.task.stop())
        self.assertIsNone(self.task.running_pid())
        self.assertFalse(self.task.stop())
        self.assertEqual(len(self.releases), 1)

    def test_keys(self):
        # one process per key, its last argument
        pid = self.task.start(7)
        self.assertEqual(self.task.running_pid(7), pid)
        self.assertIsNone(self.task.running_pid(8))
        self.assertIsNone(self.task.running_pid())
        self.assertTrue(self.task.stop(7))

    def test_crash_at_start(self):
        with self.assertRaises(FakeError) as e:
            self.task.start("crash")
        self.assertEqual(
            str(e.exception),
            "the fake stopped right after starting: boom",
        )
        self.assertEqual(len(self.releases), 1)

    def test_kill_after_stop_wait(self):
        self.task.start("stubborn")
        self.assertTrue(self.task.stop("stubborn"))
        # SIGKILL ends it a moment later
        self.children[-1].wait()
        self.assertIsNone(self.task.running_pid("stubborn"))
        self.assertEqual(
            self.task.status["stubborn"]["state"],
            "stopped",
        )

    def test_not_owner_bound(self):
        self.task.owner_bound = False
        self.task.start()
        self.assertTrue(self.task.stop())
        self.assertEqual(self.claims, [])
        self.assertEqual(self.releases, [])

    def test_check_start_and_owner(self):
        def refuse(key):
            raise FakeError("no fakes saved")

        self.task.check_start = refuse
        with self.assertRaisesRegex(FakeError, "no fakes"):
            self.task.start()
        del self.task.check_start

        def owned(force):
            raise process.tasks_owner.OwnerError("phone")

        with mock.patch.object(
            process.tasks_owner, "claim", owned
        ):
            with self.assertRaisesRegex(FakeError, "phone"):
                self.task.start(force=True)
        self.assertEqual(self.task.status, {})


if __name__ == "__main__":
    unittest.main()

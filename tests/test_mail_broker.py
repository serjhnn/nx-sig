# tests of scripts/engines/mail_broker.py
#
#   python tests/test_mail_broker.py
#
# the process is faked (spawn, process_runs), the data
# folder is a temporary one

import os
import sys
import tempfile
import unittest
from unittest import mock

import paths  # noqa: F401, scripts/ on sys.path
import config
import process
import storage
import tasks_owner
from engines import mail_broker


class FakeChild:
    def __init__(self, pid, code=None):
        self.pid = pid
        self.code = code

    def poll(self):
        return self.code


class MailBrokerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.patch(storage, "DB_DIR", tmp.name)
        self.patch(config, "DEMO", False)
        self.patch(process, "START_CHECK_SECONDS", 0)
        self.patch(mail_broker.TASK, "start_check", 0)
        self.alive = set()
        self.runs = []

        def process_runs(pid, *args):
            self.runs.append(args)
            return pid in self.alive

        self.patch(process, "process_runs", process_runs)
        self.claims = []
        self.patch(tasks_owner, "claim", self.claims.append)
        self.patch(
            process, "release_if_idle", lambda **k: None
        )

    def patch(self, target, name, value):
        p = mock.patch.object(target, name, value)
        p.start()
        self.addCleanup(p.stop)

    def test_start(self):
        spawned = []

        def spawn(args, out, wake=True, python=None):
            spawned.append((args, wake, python))
            return FakeChild(500)

        self.patch(process, "spawn", spawn)
        self.assertEqual(mail_broker.start(True), 500)
        # the shell's Python is 3.14: no other one
        self.assertEqual(
            spawned, [([mail_broker.SCRIPT], True, None)]
        )
        self.assertEqual(self.claims, [True])
        self.assertEqual(mail_broker.status()["pid"], 500)
        self.alive.add(500)
        self.assertEqual(mail_broker.running_pid(), 500)
        # the script, without an argument to check
        self.assertEqual(
            self.runs[-1], ("order_watcher.py", None)
        )
        with self.assertRaisesRegex(
            mail_broker.MailBrokerError, "already runs"
        ):
            mail_broker.start()
        self.assertEqual(len(spawned), 1)

    def test_start_fails(self):
        self.patch(
            process,
            "spawn",
            lambda *a, **k: FakeChild(5, 1),
        )
        self.patch(mail_broker.TASK, "start_check", 1)
        self.patch(
            process, "last_line", lambda files: "LOGIN"
        )
        with self.assertRaisesRegex(
            mail_broker.MailBrokerError,
            "the mail broker stopped right after "
            "starting: LOGIN",
        ):
            mail_broker.start()

    def test_not_in_demo(self):
        config.DEMO = True
        with self.assertRaisesRegex(
            mail_broker.MailBrokerError, "not in the demo"
        ):
            mail_broker.start()
        self.assertEqual(self.claims, [])

    def test_waits(self):
        # the IMAP login and logout take longer
        self.assertEqual(mail_broker.TASK.stop_wait, 20)
        self.assertEqual(mail_broker.START_CHECK_SECONDS, 3)

    def test_save_status(self):
        storage.watcher_status_set(
            {
                "pid": 1,
                "started": "2026-10-01T10:00:00",
                "state": "stopped",
                "last_order": "BUY 10 SOXL",
                "last_error": {"time": "x", "text": "y"},
            }
        )
        mail_broker.save_status(2, None, "starting")
        status = mail_broker.status()
        self.assertEqual(status["pid"], 2)
        self.assertEqual(status["state"], "starting")
        self.assertEqual(
            status["started"], "2026-10-01T10:00:00"
        )
        self.assertEqual(
            status["last_order"], "BUY 10 SOXL"
        )
        self.assertEqual(status["last_error"]["text"], "y")

    def test_tasks_run(self):
        # the mail broker keeps the background tasks
        # until it ends
        self.assertFalse(process.tasks_run())
        mail_broker.save_status(500, None, "connected")
        self.alive.add(500)
        self.assertTrue(process.tasks_run())
        self.assertFalse(
            process.tasks_run(
                ending=(mail_broker.TASK, None)
            )
        )


class FindPythonTest(unittest.TestCase):
    def old(self):
        return mock.patch.object(
            mail_broker.sys, "version_info", (3, 12, 0)
        )

    def test_new_enough(self):
        self.assertIsNone(mail_broker.find_python())

    def test_watcher_python(self):
        env = {"WATCHER_PYTHON": sys.executable}
        with self.old(), mock.patch.dict(os.environ, env):
            self.assertEqual(
                mail_broker.find_python(), sys.executable
            )

    def test_first_new_enough(self):
        tried = []

        def which(name):
            return f"/bin/{name}"

        def new_enough(path):
            tried.append(path)
            return path == "/bin/python3"

        with (
            self.old(),
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(
                mail_broker.shutil, "which", which
            ),
            mock.patch.object(
                mail_broker, "_new_enough", new_enough
            ),
        ):
            self.assertEqual(
                mail_broker.find_python(), "/bin/python3"
            )
        self.assertEqual(
            tried, ["/bin/python3.14", "/bin/python3"]
        )

    def test_none(self):
        with (
            self.old(),
            mock.patch.object(
                mail_broker.shutil,
                "which",
                lambda name: None,
            ),
        ):
            with self.assertRaisesRegex(
                mail_broker.MailBrokerError,
                "WATCHER_PYTHON",
            ):
                mail_broker.find_python()

    def test_new_enough_check(self):
        # the real check, with this Python (3.14)
        self.assertTrue(
            mail_broker._new_enough(sys.executable)
        )
        self.assertFalse(
            mail_broker._new_enough("/no/such/python")
        )


if __name__ == "__main__":
    unittest.main()

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
from datetime import datetime, timedelta
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

    def test_log_tail(self):
        self.assertEqual(mail_broker.log_tail(), [])
        path = mail_broker.log_path()
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as f:
            f.write(
                "".join(f"line {n}\n\n" for n in range(9))
            )
        self.assertEqual(
            mail_broker.log_tail(3),
            ["line 6", "line 7", "line 8"],
        )

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


class SummaryTest(unittest.TestCase):
    """mail_broker.summary() and task(): what 'status',
    'ls tasks' and the web page show"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for target, name, value in (
            (storage, "DB_DIR", tmp.name),
            (config, "DEMO", False),
        ):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.now = datetime.now().replace(microsecond=0)

    def beat(self, ago=0, **values):
        updated = self.now - timedelta(seconds=ago)
        heartbeat = {
            "pid": 7,
            "started": self.now.isoformat(),
            "updated": updated.isoformat(),
            "log": "/x/mtsig.log",
        }
        heartbeat.update(values)
        storage.watcher_status_set(heartbeat)

    def test_demo(self):
        with mock.patch.object(config, "DEMO", True):
            self.assertEqual(
                mail_broker.summary()["state"], "demo"
            )

    def test_not_started_and_unknown(self):
        self.assertEqual(
            mail_broker.summary()["state"], "not started"
        )
        storage.watcher_status_set({"updated": "x"})
        self.assertEqual(
            mail_broker.summary()["state"], "unknown"
        )

    def test_states(self):
        stale = mail_broker.STALE_SECONDS + 1
        for raw, ago, state in (
            ("connected", 0, "running"),
            ("waiting", 0, "running"),
            ("stopped", stale, "stopped"),
            ("connected", stale, "no reply"),
            ("crashed: no key", 0, "crashed: no key"),
        ):
            self.beat(ago, state=raw)
            info = mail_broker.summary()
            self.assertEqual(info["state"], state, raw)
            self.assertEqual(
                info["updated"],
                self.now - timedelta(seconds=ago),
            )
            # the log only when it is worth a look: a
            # crash or an old heartbeat
            worth = ago or raw.startswith("crashed")
            self.assertEqual(
                info["log"],
                "/x/mtsig.log" if worth else None,
                raw,
            )

    def test_last_order_and_error(self):
        old = self.now - timedelta(
            days=mail_broker.ERROR_DAYS
        )
        self.beat(
            state="waiting",
            last_order="BUY 10 SOXL",
            last_error={
                "time": old.isoformat(),
                "text": "old",
            },
        )
        info = mail_broker.summary()
        self.assertEqual(info["last_order"], "BUY 10 SOXL")
        self.assertIsNone(info["error"])
        self.assertIsNone(info["log"])
        self.beat(
            state="waiting",
            last_error={
                "time": self.now.isoformat(),
                "text": "can't parse",
            },
        )
        info = mail_broker.summary()
        self.assertEqual(
            info["error"],
            {"time": self.now, "text": "can't parse"},
        )
        self.assertEqual(info["log"], "/x/mtsig.log")

    def test_task(self):
        with mock.patch.object(
            mail_broker, "running_pid", lambda: None
        ):
            self.assertIsNone(mail_broker.task())
        self.beat(state="connected")
        with mock.patch.object(
            mail_broker, "running_pid", lambda: 7
        ):
            row = mail_broker.task()
            self.assertEqual(
                row,
                {
                    "id": "-",
                    "task": "mail-broker",
                    "pid": 7,
                    "started": self.now,
                    "state": "connected",
                    "healthy": True,
                },
            )
            self.beat(
                mail_broker.STALE_SECONDS + 1,
                state="connected",
            )
            row = mail_broker.task()
            self.assertEqual(row["state"], "no reply")
            self.assertFalse(row["healthy"])


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

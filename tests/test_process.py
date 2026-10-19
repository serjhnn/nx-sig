# tests of scripts/process.py
#
#   python tests/test_process.py

import os
import subprocess
import sys
import tempfile

import unittest

import paths  # noqa: F401, scripts/ on sys.path
from unittest import mock

from process import (
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


if __name__ == "__main__":
    unittest.main()

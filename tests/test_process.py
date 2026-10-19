# tests of scripts/process.py
#
#   python tests/test_process.py

import os
import subprocess
import sys
import tempfile

import unittest

import paths  # noqa: F401, scripts/ on sys.path
from process import (
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

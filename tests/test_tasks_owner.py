# tests of scripts/tasks_owner.py
#
#   python tests/test_tasks_owner.py

import os

import unittest
from unittest import mock

import paths  # noqa: F401, scripts/ on sys.path
import storage
from tasks_owner import (
    OwnerError,
    _main,
    claim,
    describe,
    lost,
    owner,
    release,
    this_device,
)

import tempfile


class OwnerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._db_dir = storage.DB_DIR
        storage.DB_DIR = self._tmp.name
        self.phone = os.path.join(
            self._tmp.name, "phone.device"
        )
        self.pc = os.path.join(self._tmp.name, "pc.device")
        self.on_phone()

    def tearDown(self):
        mock.patch.stopall()
        storage.DB_DIR = self._db_dir
        self._tmp.cleanup()

    def on_phone(self):
        mock.patch.stopall()
        mock.patch(
            "tasks_owner.DEVICE_PATH", self.phone
        ).start()
        mock.patch.dict(
            os.environ, {"TERMUX_VERSION": "1"}
        ).start()

    def on_pc(self):
        mock.patch.stopall()
        mock.patch(
            "tasks_owner.DEVICE_PATH", self.pc
        ).start()
        # restored by stopall
        mock.patch.dict(os.environ).start()
        os.environ.pop("TERMUX_VERSION", None)

    def test_device_is_kept(self):
        device = this_device()
        self.assertEqual(device["name"], "phone")
        self.assertEqual(this_device(), device)
        self.on_pc()
        self.assertNotEqual(
            this_device()["id"], device["id"]
        )
        self.assertNotEqual(this_device()["name"], "phone")

    def test_claim_without_owner(self):
        self.assertIsNone(owner())
        self.assertIsNone(claim())
        self.assertEqual(owner()["name"], "phone")
        self.assertFalse(lost())
        # again: still the owner, since kept
        since = owner()["since"]
        self.assertIsNone(claim())
        self.assertEqual(owner()["since"], since)

    def test_other_device_is_refused(self):
        claim()
        self.on_pc()
        self.assertTrue(lost())
        with self.assertRaises(OwnerError) as e:
            claim()
        self.assertIn("phone (since", str(e.exception))
        self.assertIn("'force'", str(e.exception))
        self.assertEqual(owner()["name"], "phone")

    def test_force_takes_over(self):
        claim()
        self.on_pc()
        taken = claim(force=True)
        self.assertEqual(taken["name"], "phone")
        self.assertFalse(lost())
        # the phone's tasks see it and stop
        self.on_phone()
        self.assertTrue(lost())

    def test_release(self):
        claim()
        # another device can't release it
        self.on_pc()
        release()
        self.assertEqual(owner()["name"], "phone")
        self.on_phone()
        release()
        self.assertIsNone(owner())
        self.assertFalse(lost())
        # nothing to release
        release()
        self.on_pc()
        self.assertIsNone(claim())

    def test_broken_file_is_no_owner(self):
        with open(
            os.path.join(
                storage.DB_DIR, "tasks_owner.json"
            ),
            "w",
        ) as f:
            f.write("{not json")
        self.assertIsNone(owner())
        self.assertIsNone(claim())

    def test_describe(self):
        self.assertEqual(
            describe(
                {
                    "name": "pc",
                    "since": "2026-10-16T14:30:00",
                }
            ),
            "pc (since 16.10 14:30)",
        )
        self.assertEqual(describe({"name": "pc"}), "pc")

    def test_main(self):
        self.assertEqual(_main(["claim"]), 0)
        self.on_pc()
        with mock.patch("sys.stderr"):
            self.assertEqual(_main(["claim"]), 1)
            self.assertEqual(_main(["bad"]), 2)
        with mock.patch("sys.stdout"):
            self.assertEqual(_main(["claim", "force"]), 0)
        self.assertEqual(_main(["release"]), 0)
        self.assertIsNone(owner())


if __name__ == "__main__":
    unittest.main()

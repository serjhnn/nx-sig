# tasks_owner: only one device runs the background tasks
# (the mail broker and the ladders)
#
# data/ is synced between the phone and the PC, so both
# see the same emails and ladders: the mail broker on
# both would record every order twice. tasks_owner.json
# (synced) names the device that runs them:
#   - a task starts only if no other device owns them,
#     or with force, when the other device crashed or is
#     off
#   - when this device's last task stops, it releases
#     them
#   - a running task stops itself when it sees that
#     another device took them over (after a sync)
# the devices sync only when they reach each other, so
# tasks started on both while apart run until the next
# sync; then the later owner wins and the other stops.
#
# each device keeps its own id in .device in the repo
# folder, not in data/, so it is never synced
#
#   python scripts/tasks_owner.py claim [force]
#   python scripts/tasks_owner.py release
#       for ./mtsig; claim prints why and exits 1 if
#       another device owns them
#   python scripts/tasks_owner.py
#       run the tests
#
# public functions:
#   this_device()
#       {"id", "name"} of this device
#   owner()
#       {"id", "name", "since"} of the owner, or None
#   claim(force=False)
#       make this device the owner; return the owner it
#       took them over from, or None; raise OwnerError
#       if another device owns them and not force
#   release()
#       clear the owner if it is this device
#   lost()
#       True if another device owns them
#   describe(owner)
#       'phone (since 16.10 14:30)'

import json
import os
import platform
import sys
import uuid
from datetime import datetime

import storage
from storage import (
    ROOT_DIR,
    tasks_owner_get,
    tasks_owner_set,
)

DEVICE_PATH = os.path.join(ROOT_DIR, ".device")
# a device name longer than this is cut, so the lines
# about it fit the shell
NAME_LENGTH = 12


class OwnerError(Exception):
    """another device runs the background tasks; the
    text says which and what to do"""


def this_device():
    """this device's id and name, from DEVICE_PATH; the
    first call writes it: a random id, and 'phone' in
    Termux or the host name"""
    try:
        with open(DEVICE_PATH) as f:
            device = json.load(f)
        if device.get("id") and device.get("name"):
            return device
    except (OSError, ValueError):
        pass
    if "TERMUX_VERSION" in os.environ:
        name = "phone"
    else:
        name = platform.node().split(".")[0] or "pc"
    device = {
        "id": uuid.uuid4().hex,
        "name": name[:NAME_LENGTH],
    }
    with open(DEVICE_PATH, "w") as f:
        json.dump(device, f, indent=4)
    return device


def owner():
    current = tasks_owner_get()
    if not isinstance(current, dict) or not current.get(
        "id"
    ):
        return None
    return current


def describe(current):
    """'phone (since 16.10 14:30)'"""
    try:
        since = datetime.fromisoformat(current["since"])
    except (KeyError, TypeError, ValueError):
        return current.get("name", "?")
    name = current.get("name", "?")
    return f"{name} (since {since:%d.%m %H:%M})"


def lost():
    current = owner()
    return bool(current) and (
        current["id"] != this_device()["id"]
    )


def claim(force=False):
    """make this device the owner of the background
    tasks before one starts"""
    me = this_device()
    current = owner()
    if current and current["id"] == me["id"]:
        return None
    if current and not force:
        raise OwnerError(
            f"{describe(current)} runs the background "
            "tasks: stop them there, or add 'force' "
            "if it is off"
        )
    tasks_owner_set(
        {
            "id": me["id"],
            "name": me["name"],
            "since": datetime.now().isoformat(
                timespec="seconds"
            ),
        }
    )
    return current


def release():
    """after this device's last task stopped"""
    current = owner()
    if current and current["id"] == this_device()["id"]:
        tasks_owner_set(None)


def _main(args):
    if args in (["claim"], ["claim", "force"]):
        try:
            taken = claim(force=len(args) == 2)
        except OwnerError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if taken:
            print(
                "took over the background tasks from "
                f"{describe(taken)}"
            )
        return 0
    if args == ["release"]:
        release()
        return 0
    print(
        "usage: tasks_owner.py claim [force] | release",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__" and len(sys.argv) > 1:
    sys.exit(_main(sys.argv[1:]))

elif __name__ == "__main__":
    import tempfile
    import unittest
    from unittest import mock

    class OwnerTest(unittest.TestCase):
        def setUp(self):
            self._tmp = tempfile.TemporaryDirectory()
            self._db_dir = storage.DB_DIR
            storage.DB_DIR = self._tmp.name
            self.phone = os.path.join(
                self._tmp.name, "phone.device"
            )
            self.pc = os.path.join(
                self._tmp.name, "pc.device"
            )
            self.on_phone()

        def tearDown(self):
            mock.patch.stopall()
            storage.DB_DIR = self._db_dir
            self._tmp.cleanup()

        def on_phone(self):
            mock.patch.stopall()
            mock.patch(
                f"{__name__}.DEVICE_PATH", self.phone
            ).start()
            mock.patch.dict(
                os.environ, {"TERMUX_VERSION": "1"}
            ).start()

        def on_pc(self):
            mock.patch.stopall()
            mock.patch(
                f"{__name__}.DEVICE_PATH", self.pc
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
            self.assertNotEqual(
                this_device()["name"], "phone"
            )

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
                self.assertEqual(
                    _main(["claim", "force"]), 0
                )
            self.assertEqual(_main(["release"]), 0)
            self.assertIsNone(owner())

    unittest.main()

# tests of scripts/notifier.py
#
#   python tests/test_notifier.py

import importlib

import unittest
from unittest import mock

import paths  # noqa: F401, scripts/ on sys.path
import config
from notifier import (
    CHANNELS,
    NAME,
    channel,
)

import termux_notify


class NotifierTest(unittest.TestCase):
    def test_channel_of_config(self):
        self.assertEqual(channel.__name__, CHANNELS[NAME])

    def test_unknown_channel(self):
        import sys

        with mock.patch.dict(
            config.DATA, {"notify": "mail"}
        ), mock.patch.dict(sys.modules):
            sys.modules.pop("notifier", None)
            with self.assertRaises(ValueError) as e:
                importlib.import_module("notifier")
        self.assertIn("'mail'", str(e.exception))

    def test_termux_notify(self):
        with mock.patch.object(
            termux_notify.subprocess, "run"
        ) as run:
            termux_notify.notify("SOXL up")
        args = run.call_args.args[0]
        self.assertEqual(args[0], "termux-notification")
        self.assertEqual(
            args[args.index("--content") + 1],
            "SOXL up",
        )
        self.assertTrue(run.call_args.kwargs["check"])

    def test_termux_is_configured(self):
        which = "termux_notify.shutil.which"
        with mock.patch(which, return_value=None):
            self.assertFalse(termux_notify.is_configured())
        with mock.patch(which, return_value="/bin/t"):
            self.assertTrue(termux_notify.is_configured())


if __name__ == "__main__":
    unittest.main()

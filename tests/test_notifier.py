# tests of scripts/notifiers/notifier.py
#
#   python tests/test_notifier.py

import importlib

import unittest
from unittest import mock

import paths  # noqa: F401, scripts/ on sys.path
import config
from notifiers.notifier import (
    CHANNELS,
    NAME,
    channel,
)

from notifiers import ntfy_notify, termux_notify


class NotifierTest(unittest.TestCase):
    def test_channel_of_config(self):
        self.assertEqual(
            channel.__name__,
            f"notifiers.{CHANNELS[NAME]}",
        )

    def test_unknown_channel(self):
        import sys

        with mock.patch.dict(
            config.DATA, {"notify": "mail"}
        ), mock.patch.dict(sys.modules):
            sys.modules.pop("notifiers.notifier", None)
            with self.assertRaises(ValueError) as e:
                importlib.import_module(
                    "notifiers.notifier"
                )
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
        which = "notifiers.termux_notify.shutil.which"
        with mock.patch(which, return_value=None):
            self.assertFalse(termux_notify.is_configured())
        with mock.patch(which, return_value="/bin/t"):
            self.assertTrue(termux_notify.is_configured())

    def test_ntfy_channel(self):
        import sys

        import notifiers

        # the import sets notifiers.notifier, put the
        # one the other tests use back after
        with mock.patch.dict(
            config.DATA, {"notify": "ntfy"}
        ), mock.patch.dict(sys.modules), mock.patch.object(
            notifiers, "notifier", notifiers.notifier
        ):
            sys.modules.pop("notifiers.notifier", None)
            mod = importlib.import_module(
                "notifiers.notifier"
            )
        self.assertIs(mod.channel, ntfy_notify)

    def test_ntfy_notify(self):
        env = {"NTFY_TOPIC": "nx-test"}
        with mock.patch.dict(
            "os.environ", env
        ), mock.patch.object(
            ntfy_notify.requests, "post"
        ) as post:
            ntfy_notify.notify("SOXL up")
        self.assertEqual(
            post.call_args.args[0],
            "https://ntfy.sh/nx-test",
        )
        self.assertEqual(
            post.call_args.kwargs["data"], b"SOXL up"
        )
        resp = post.return_value
        resp.raise_for_status.assert_called_once()

    def test_ntfy_is_configured(self):
        with mock.patch.dict(
            "os.environ", {"NTFY_TOPIC": ""}
        ):
            self.assertFalse(ntfy_notify.is_configured())
        with mock.patch.dict(
            "os.environ", {"NTFY_TOPIC": "t"}
        ):
            self.assertTrue(ntfy_notify.is_configured())


if __name__ == "__main__":
    unittest.main()

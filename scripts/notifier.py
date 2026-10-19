# notifier: sends the ladder and alert messages through
# the channel of config.json "notify":
#   "telegram"  telegram_notify.py, a Telegram bot
#               (TOKEN, CHAT_ID in .env), the default
#   "termux"    termux_notify.py, an Android
#               notification through Termux:API
# only the chosen module is imported.
#
#   python scripts/notifier.py   run the tests
#
#   NAME             the channel name
#   notify(text)     send text, raises if it fails
#   is_configured()  True if the channel can send
#   setup_error()    why it can't, for the shell

import importlib

from storage import config

CHANNELS = {
    "telegram": "telegram_notify",
    "termux": "termux_notify",
}

NAME = config.get("notify", "telegram")
if NAME not in CHANNELS:
    raise ValueError(
        'config.json "notify" must be '
        + " or ".join(f'"{n}"' for n in CHANNELS)
        + f", not {NAME!r}"
    )
channel = importlib.import_module(CHANNELS[NAME])


def notify(text):
    """send text through the chosen channel"""
    return channel.notify(text)


def is_configured():
    """True if the chosen channel can send"""
    return channel.is_configured()


def setup_error():
    """the error to print when it can't send"""
    return channel.SETUP_ERROR


if __name__ == "__main__":
    import unittest
    from unittest import mock

    import termux_notify

    class NotifierTest(unittest.TestCase):
        def test_channel_of_config(self):
            self.assertEqual(
                channel.__name__, CHANNELS[NAME]
            )

        def test_unknown_channel(self):
            import sys

            with mock.patch.dict(
                config, {"notify": "mail"}
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
                self.assertFalse(
                    termux_notify.is_configured()
                )
            with mock.patch(which, return_value="/bin/t"):
                self.assertTrue(
                    termux_notify.is_configured()
                )

    unittest.main()

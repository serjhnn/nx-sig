# termux_notify: a message as an Android notification
# through Termux:API, the notify channel "termux" of
# config.json (see notifier.py). needs the Termux:API
# app and 'pkg install termux-api'; no internet, no keys
#
#   python scripts/termux_notify.py   send a test
#
#   is_configured()  True if termux-notification is
#                    installed
#   notify(text)     one new notification per message,
#                    raises if it can't be shown
#   SETUP_ERROR      what to do when it isn't set up

import shutil
import subprocess
import time

SETUP_ERROR = (
    "error: Termux:API isn't set up, install the "
    "Termux:API app and run 'pkg install termux-api'"
)


def is_configured():
    """True if termux-notification is installed"""
    return shutil.which("termux-notification") is not None


def notify(text, title="nX-sig"):
    """show text as its own notification; it hangs
    without the Termux:API app, so it has a timeout"""
    subprocess.run(
        [
            "termux-notification",
            "--id",
            f"nx-sig-{time.time_ns()}",
            "--title",
            title,
            "--content",
            text,
            "--priority",
            "high",
        ],
        check=True,
        capture_output=True,
        timeout=15,
    )


if __name__ == "__main__":
    notify("test notification")

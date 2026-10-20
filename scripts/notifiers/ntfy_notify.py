# ntfy_notify: a push notification through ntfy.sh,
# the notify channel "ntfy" of config.json (see
# notifier.py). the phone needs the ntfy app subscribed
# to the topic NTFY_TOPIC of .env
#
#   python scripts/notifiers/ntfy_notify.py  send a test
#
#   is_configured()  True if NTFY_TOPIC is set
#   notify(text, title, key=None)
#                    send text, raises if it fails. with a
#                    key it is posted to <topic>/<key>, the
#                    sequence id, which updates the earlier
#                    message (needs a recent ntfy server
#                    and app)
#   SETUP_ERROR      what to do when it isn't set up

import requests
import os
from dotenv import load_dotenv

# .env lives in the repo root, two levels above
# scripts/notifiers/
HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(
    os.path.join(
        os.path.dirname(os.path.dirname(HERE)), ".env"
    )
)

SETUP_ERROR = (
    "error: ntfy isn't set up, add NTFY_TOPIC to .env"
)


def is_configured():
    """True if NTFY_TOPIC is set in .env"""
    return bool(os.getenv("NTFY_TOPIC"))


def notify(text, title="nX-sig", key=None):
    """send text to the topic, raises if it fails"""
    url = f"https://ntfy.sh/{os.environ["NTFY_TOPIC"]}"
    if key:
        url += f"/{key}"
    resp = requests.post(
        url,
        data=text.encode(),
        headers={"Title": title, "Priority": "default"},
        timeout=10,
    )
    resp.raise_for_status()


if __name__ == "__main__":
    notify("test notification")

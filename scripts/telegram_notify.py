# telegram_notify: a message through a Telegram bot,
# the notify channel "telegram" of config.json (see
# notifier.py)

import requests
import os
from dotenv import load_dotenv

# .env lives in the repo root, one level above scripts/
load_dotenv(
    os.path.join(
        os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        ),
        ".env",
    )
)

SETUP_ERROR = (
    "error: Telegram isn't set up, add TOKEN and "
    "CHAT_ID to .env"
)


def is_configured():
    """True if TOKEN and CHAT_ID are set in .env"""
    return bool(os.getenv("TOKEN") and os.getenv("CHAT_ID"))


def notify(text):
    resp = requests.post(
        "https://api.telegram.org/bot"
        f"{os.environ["TOKEN"]}/sendMessage",
        data={
            "chat_id": os.environ["CHAT_ID"],
            "text": text,
        },
        timeout=10,
    )
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram error: {data}")
    return data


if __name__ == "__main__":
    print(notify("test TOKEN "))

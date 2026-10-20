# notifier: sends the ladder and alert messages through
# the channel of config.json "notify":
#   "telegram"  telegram_notify.py, a Telegram bot
#               (TOKEN, CHAT_ID in .env), the default
#   "termux"    termux_notify.py, an Android
#               notification through Termux:API
#   "ntfy"      ntfy_notify.py, a push through
#               ntfy.sh (NTFY_TOPIC in .env)
# only the chosen module is imported.
#
#   python tests/test_notifier.py  the tests
#
#   NAME             the channel name
#   notify(text, key=None)
#                    send text, raises if it fails. the
#                    same key again replaces the earlier
#                    message where the channel can
#                    (termux, ntfy), else it is a new one
#   is_configured()  True if the channel can send
#   setup_error()    why it can't, for the shell

import importlib

import config

CHANNELS = {
    "telegram": "telegram_notify",
    "termux": "termux_notify",
    "ntfy": "ntfy_notify",
}

# config.notify() raises ValueError for another name
NAME = config.notify()
channel = importlib.import_module(
    f"notifiers.{CHANNELS[NAME]}"
)


def notify(text, key=None):
    """send text through the chosen channel; with a key
    the channel replaces the message of that key"""
    if key is None:
        return channel.notify(text)
    return channel.notify(text, key=key)


def is_configured():
    """True if the chosen channel can send"""
    return channel.is_configured()


def setup_error():
    """the error to print when it can't send"""
    return channel.SETUP_ERROR

# notifier: sends the ladder and alert messages through
# the channel of config.json "notify":
#   "telegram"  telegram_notify.py, a Telegram bot
#               (TOKEN, CHAT_ID in .env), the default
#   "termux"    termux_notify.py, an Android
#               notification through Termux:API
# only the chosen module is imported.
#
#   python tests/test_notifier.py  the tests
#
#   NAME             the channel name
#   notify(text)     send text, raises if it fails
#   is_configured()  True if the channel can send
#   setup_error()    why it can't, for the shell

import importlib

import config

CHANNELS = {
    "telegram": "telegram_notify",
    "termux": "termux_notify",
}

# config.notify() raises ValueError for another name
NAME = config.notify()
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

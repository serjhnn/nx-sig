# demo_notify: the notify channel of the demo
# (./nxdemo), used instead of config.json "notify"
# (see notifier.py): a message is kept in the demo's
# data (engines/demo.py) and the demo shell prints it
# after the next command. no internet, no keys
#
#   is_configured()  always True
#   notify(text, key=None)
#                    keep text; key is not used, every
#                    message is shown
#   SETUP_ERROR      never needed

from engines import demo

SETUP_ERROR = ""


def is_configured():
    return True


def notify(text, key=None):
    demo.message_add(text)

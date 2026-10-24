# demo_cmd: the shell side of the demo (./nxdemo)
#
# print_messages() prints the messages of the ladders
# and alerts that came since the last command (the
# demo's notify channel, notifiers/demo_notify.py);
# demo_status() is the demo's line in 'status'

import config
from engines import demo, demo_prices
from shell.ui import (
    BOLD,
    PRICE_COLOR,
    RESET,
    print_error,
    print_wrapped,
    supports_color,
)

# marks what the demo made up
TAG = "[DEMO]"


def print_messages():
    """print the new messages, each with its time"""
    if not config.demo():
        return
    for message in demo.messages_new():
        tag = TAG
        if supports_color():
            tag = f"{BOLD}{PRICE_COLOR}{TAG}{RESET}"
        print_error(
            f"{tag} {message['Time']} {message['Text']}"
        )


def demo_status():
    """the line about the demo's prices"""
    pid = demo_prices.running_pid()
    interval = config.demo_number("interval")
    if pid:
        state = f"moving every {interval}s (pid {pid})"
    else:
        state = "not moving, restart ./nxdemo"
    print_wrapped(f"demo: made-up prices, {state}")

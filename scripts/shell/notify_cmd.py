# notify_cmd: sends a test message through the config
# "notify" channel (notifiers/notifier.py)
#
#   test notify <alert|ladder> [repeat <n>]
#
# NotifyCmd is mixed into NxSigShell: a command of its
# own, not a kind of data

import time

from notifiers import notifier
from shell.ui import (
    complete_options,
    print_error,
    print_wrapped,
    stock_names,
)

USAGE = "usage: test notify <alert|ladder> [repeat <n>]"
KINDS = ("alert", "ladder")
# repeated messages share this key, so a channel that
# can replace a message shows them as one
KEY = "test"
MAX_REPEAT = 20
PAUSE = 5  # seconds between repeated messages


def _sample(kind):
    """a message like a real one of kind, marked test"""
    stock = stock_names()[0]
    if kind == "ladder":
        return (
            f"test: {stock} down to 89.50, passed 90 "
            "(ladder 0, next 80)"
        )
    return (
        f"test: {stock} -10.5% at 17.90, bought at 20 "
        "(alert 0: down 10%)"
    )


class NotifyCmd:
    def do_test(self, arg):
        """
        test notify <alert|ladder> [repeat <n>]
            send a test message like an alert's or
            a ladder's through config.json "notify"
            (telegram, termux or ntfy), to check
            that it arrives. with 'repeat <n>' it
            is sent n times, 5 seconds apart, all
            with the same id: termux and ntfy then
            update one notification, to see how a
            watch shows an updated one
        """
        args = arg.lower().split()
        count = 1
        if len(args) == 4 and args[2] == "repeat":
            if not args[3].isdigit() or not (
                1 <= int(args[3]) <= MAX_REPEAT
            ):
                print_error(
                    f"repeat must be 1-{MAX_REPEAT}, "
                    f"not '{args[3]}'"
                )
                return
            count = int(args[3])
            args = args[:2]
        if len(args) != 2 or args[0] != "notify":
            print_wrapped(USAGE)
            return
        if args[1] not in KINDS:
            print_error(
                f"unknown kind '{args[1]}', expected "
                + "/".join(KINDS)
            )
            return
        if not notifier.is_configured():
            print_error(notifier.setup_error())
            return
        text = _sample(args[1])
        for i in range(1, count + 1):
            if i > 1:
                time.sleep(PAUSE)
            try:
                if count == 1:
                    notifier.notify(text)
                else:
                    notifier.notify(
                        f"{text} [{i}/{count}]", KEY
                    )
            except Exception as e:
                print_error(f"error: could not send: {e}")
                return
            if count > 1:
                print_wrapped(f"sent {i}/{count}")
        times = ""
        if count > 1:
            times = f" {count} times, id {KEY}"
        print_wrapped(
            f"sent a test {args[1]} message "
            f"({notifier.NAME}){times}"
        )

    def complete_test(self, text, line, begidx, endidx):
        options = [["notify"], list(KINDS), ["repeat"]]
        return complete_options(text, line, options)

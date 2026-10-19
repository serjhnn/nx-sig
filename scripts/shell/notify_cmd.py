# notify_cmd: sends a test message through the config
# "notify" channel (notifiers/notifier.py)
#
#   test notify <alert|ladder>
#
# NotifyCmd is mixed into NxSigShell: a command of its
# own, not a kind of data

from notifiers import notifier
from shell.ui import (
    complete_options,
    print_error,
    print_wrapped,
    stock_names,
)

USAGE = "usage: test notify <alert|ladder>"
KINDS = ("alert", "ladder")


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
        test notify <alert|ladder>
            send a test message like an alert's or
            a ladder's through config.json "notify"
            (telegram, termux or ntfy), to check
            that it arrives
        """
        args = arg.lower().split()
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
        try:
            notifier.notify(_sample(args[1]))
        except Exception as e:
            print_error(f"error: could not send: {e}")
            return
        print_wrapped(
            f"sent a test {args[1]} message "
            f"({notifier.NAME})"
        )

    def complete_test(self, text, line, begidx, endidx):
        return complete_options(
            text, line, [["notify"], list(KINDS)]
        )

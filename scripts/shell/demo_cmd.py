# demo_cmd: the shell side of the demo (./nxdemo)
#
#   demo set <stock> <price>
#   demo move <stock|all> <n>%
#   demo speed [<n>]
#   demo reset
#   demo tour
#
# DemoCmd is mixed into NxSigShell: a command of its
# own, which works only in the demo.
# print_messages() prints the messages of the ladders
# and alerts that came since the last command (the
# demo's notify channel, notifiers/demo_notify.py);
# demo_status() is the demo's line in 'status'

import config
from engines import demo, demo_prices
from engines.demo_prices import DemoPricesError
from shell.ui import (
    BOLD,
    PRICE_COLOR,
    RESET,
    complete_options,
    confirm,
    parse_stock,
    print_error,
    print_wrapped,
    stock_names,
    supports_color,
)

USAGE = (
    "usage: demo set <stock> <price>, demo move "
    "<stock|all> <n>%, demo speed [<n>], demo reset, "
    "demo tour"
)
ACTIONS = ("set", "move", "speed", "reset", "tour")
# the steps of 'demo tour'
TOUR = [
    "ls stocks: the sample positions and their " "growth",
    "ls trades NVDL: the trades of a stock",
    "status: the gain or loss in money now",
    "xtop: the same, updated live (q returns)",
    "chart SOXL: the price of the last 5 days",
    "ls basetrades al: the last buying prices and "
    "the alert levels",
    "run ladder 1: a message each time SOXL falls "
    "by 1 more",
    "run alerts: a message when a stock is 15% "
    "above its basetrade",
    "demo move SOXL -5%: to see the ladder send one",
    "add trade SOXL buy count 10 price 33, then "
    "ls stocks again",
    "ls tasks, then stop tasks all",
    "help: every command; demo reset starts over",
]

# marks what the demo made up
TAG = "[DEMO]"


class DemoCmd:
    def do_demo(self, arg):
        """
        demo set <stock> <price>
        demo move <stock|all> <n>%
        demo speed [<n>]
        demo reset
        demo tour
            only in the demo (./nxdemo): set a
            price, or move one or all by n percent,
            e.g. 'demo move SOXL -5%', to see a
            ladder or an alert send a message;
            speed shows or sets how many times
            faster than real time the prices move;
            reset stops the demo's tasks and starts
            over with the sample data; tour lists
            what to try
        """
        if not config.demo():
            print_error(
                "only in the demo, start it with "
                "./nxdemo"
            )
            return
        args = arg.split()
        action = args[0].lower() if args else ""
        if action not in ACTIONS:
            print_wrapped(USAGE)
            return
        try:
            getattr(self, f"_demo_{action}")(args[1:])
        except (ValueError, DemoPricesError) as e:
            print_error(f"error: {e}")

    def _demo_set(self, args):
        if len(args) != 2:
            print_wrapped("usage: demo set <stock> <price>")
            return
        stock = parse_stock(args[0])
        price = _number(args[1], "price")
        before = demo_prices.latest()
        after = demo_prices.set_price(stock.name, price)
        _print_moves(before, after, [stock.name])

    def _demo_move(self, args):
        if len(args) != 2 or not args[1].endswith("%"):
            print_wrapped(
                "usage: demo move <stock|all> <n>%"
            )
            return
        if args[0].lower() == "all":
            names = list(config.indices())
        else:
            names = [parse_stock(args[0]).name]
        percent = _number(args[1][:-1], "percent")
        before = demo_prices.latest()
        after = demo_prices.shift(names, percent)
        _print_moves(before, after, names)

    def _demo_speed(self, args):
        if len(args) > 1:
            print_wrapped("usage: demo speed [<n>]")
            return
        if args:
            demo_prices.set_speed(_number(args[0], "speed"))
        interval = config.demo_number("interval")
        print_wrapped(
            f"speed: {demo_prices.speed():g} times "
            f"real time, a move every {interval}s"
        )

    def _demo_reset(self, args):
        if args:
            print_wrapped("usage: demo reset")
            return
        print_wrapped(
            "this stops the demo's ladders and alerts "
            "and brings back the sample data and prices"
        )
        if not confirm("start over? [y/N] "):
            print_wrapped("not reset")
            return
        stopped = demo.reset()
        tasks = "task" if stopped == 1 else "tasks"
        print_wrapped(
            "the demo starts over: sample data, new "
            f"prices; {stopped} {tasks} stopped"
        )

    def _demo_tour(self, args):
        if args:
            print_wrapped("usage: demo tour")
            return
        print_wrapped("things to try, in this order:")
        for i, step in enumerate(TOUR, 1):
            print_wrapped(f"{i:>2}. {step}")

    def complete_demo(self, text, line, begidx, endidx):
        args = line.split()
        action = args[1].lower() if len(args) > 1 else ""
        stocks = stock_names()
        if action == "move":
            stocks = stocks + ["all"]
        options = [list(ACTIONS)]
        if action in ("set", "move"):
            options.append(stocks)
        return complete_options(text, line, options)


def _number(text, name):
    try:
        return float(text)
    except ValueError:
        raise ValueError(
            f"the {name} must be a number, not '{text}'"
        ) from None


def _print_moves(before, after, names):
    for name in names:
        print_wrapped(
            f"{name}: {before.get(name, 0):.2f} -> "
            f"{after[name]:.2f}"
        )


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

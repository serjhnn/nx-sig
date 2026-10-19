# base_trade_cmd: the basetrades, the last price you
# bought each stock at
#
#   ls basetrades [al]
#   add basetrade <stock> price <price> count <count>
#   rm basetrade <stock>
#
# BaseTradeCommands implements them for the verb
# commands of commands.py

from engines import basetrades
from engines.basetrades import Stock
from shell.alert_cmd import print_basetrade_alerts
from shell.interface import Commands
from shell.ui import (
    BOLD,
    COUNT_COLOR,
    DIM,
    PRICE_COLOR,
    RESET,
    TOTAL_STOCK_COLOR,
    width,
    space_separator,
    confirm,
    fetch_prices,
    color_for_gain,
    parse_keywords,
    parse_stock,
    print_error,
    print_wrapped,
    supports_color,
)

ADD_USAGE = (
    "usage: add basetrade <stock> price <price> "
    "count <count>"
)


class BaseTradeCommands(Commands):
    # a basetrade is the last buying price you keep for
    # a stock, one per stock (base_trades.csv); it
    # doesn't change the trades or totals
    name = "basetrade"
    plural = "basetrades"
    order = 50

    def ls(self, arg):
        """
        ls basetrades [al]
            the basetrades in config order, with
            the current price of each stock and its
            change % from the buying price; with
            al, below it each alert's price per
            stock, a ! when the price is past it
        """
        args = arg.lower().split()
        if args not in ([], ["al"]):
            print_wrapped("usage: ls basetrades [al]")
            return
        self._basetrades_show(alerts=bool(args))

    def add(self, arg):
        """
        add basetrade <stock> price <price>
          count <count>
            save the last price you bought <stock>
            at and how many, e.g. 'add basetrade
            MRVU price 100 count 10'; replaces the
            stock's older basetrade
        """
        args = arg.split()
        values = parse_keywords(
            args[1:], ["price", "count"]
        )
        if not args or values is None:
            print_wrapped(ADD_USAGE)
            return
        try:
            stock = parse_stock(args[0])
        except ValueError as e:
            print_error(f"error: {e}")
            return
        try:
            price = float(values["price"])
            count = int(values["count"])
        except ValueError:
            print_error(
                "error: price must be a number and "
                "count a whole number"
            )
            return
        try:
            replaced = basetrades.save(stock, price, count)
        except basetrades.BaseTradeError as e:
            print_error(f"error: {e}")
            return
        print_wrapped(
            f"{'replaced' if replaced else 'added'} "
            f"basetrade of {stock.name}: {count} at "
            f"{price:g}"
        )

    def rm(self, arg):
        """
        rm basetrade <stock>
            delete the basetrade of <stock> after
            confirmation
        """
        args = arg.split()
        if len(args) != 1:
            print_wrapped("usage: rm basetrade <stock>")
            return
        name = args[0].upper()
        found = basetrades.get(name)
        if found is None:
            print_error(
                f"error: no basetrade of {name}, "
                "see 'ls basetrades'"
            )
            return
        if not confirm(
            f"delete basetrade of {name}: "
            f"{found['Count']} at "
            f"{found['Price']:g}? [y/N] "
        ):
            print_wrapped("cancelled")
            return
        basetrades.delete(name)
        print_wrapped(f"deleted basetrade of {name}")

    def complete(self, action, args):
        if action == "add":
            keywords = ["price", "count"]
            return [
                [s.name for s in Stock],
                keywords,
                [],
                keywords,
            ]
        if action == "rm":
            return [
                [b["Stock"] for b in basetrades.get_all()]
            ]
        if action == "ls":
            return [["al"]]
        return []

    def _basetrades_show(self, alerts=False):
        found = basetrades.get_all()
        if not found:
            print_wrapped(
                "no basetrades yet, see 'help add "
                "basetrade'"
            )
            return
        prices = fetch_prices()

        color = supports_color()
        # laid out like the xtop table, the columns
        # widened to fill DEFAULT_WIDTH
        column_sep = space_separator(5, 1)
        header_cols = [
            f"{'Name':<5}",
            f"{'Qty':>6}",
            f"{'Buy':>11}",
            f"{'Price':>11}",
            f"{'Change %':>11}",
        ]
        if color:
            header_cols = [
                f"{DIM}{col}{RESET}" for col in header_cols
            ]
        separator = "-" * width()
        print()
        print(column_sep.join(header_cols))
        print(
            f"{DIM}{separator}{RESET}"
            if color
            else separator
        )
        for b in found:
            current = prices.get(b["Stock"])
            name = f"{b['Stock']:<5.5}"
            qty = f"{b['Count']:>6}"
            buy = f"{b['Price']:>11.2f}"
            price = f"{'-':>11}"
            change = f"{'-':>11}"
            if current is not None:
                price = f"{current:>11.2f}"
                # how far the current price is from the
                # buying price
                pct = (
                    (current - b["Price"])
                    / b["Price"]
                    * 100
                )
                change = f"{pct:>+10.2f}%"
            if color:
                # the current price is green above the
                # buying price and red below it
                price_color = (
                    color_for_gain(current - b["Price"])
                    if current is not None
                    else DIM
                )
                name = (
                    f"{BOLD}{TOTAL_STOCK_COLOR}"
                    f"{name}{RESET}"
                )
                qty = f"{COUNT_COLOR}{qty}{RESET}"
                buy = f"{PRICE_COLOR}{buy}{RESET}"
                price = f"{price_color}{price}{RESET}"
                change = f"{price_color}{change}{RESET}"
            print(
                column_sep.join(
                    [name, qty, buy, price, change]
                )
            )
        print()
        if alerts:
            print_basetrade_alerts(found, prices)
            print()

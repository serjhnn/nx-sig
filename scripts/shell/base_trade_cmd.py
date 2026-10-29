# base_trade_cmd: the basetrades, the last price you
# bought each stock at
#
#   ls basetrades [sip|iex] [al]
#   add basetrade <stock>|all
#   add basetrade <stock> price <price> count <count>
#   rm basetrade <stock>
#
# BaseTradeCommands implements them for the verb
# commands of commands.py

from engines import basetrades, trades
from engines.basetrades import Stock
from shell.alert_cmd import print_basetrade_alerts
from shell.interface import Commands
from shell.ui import (
    print_table,
    rule,
    BOLD,
    COUNT_COLOR,
    DIM,
    PRICE_COLOR,
    RESET,
    TOTAL_STOCK_COLOR,
    space_separator,
    confirm,
    fetch_prices,
    color_for_gain,
    parse_keywords,
    parse_stock,
    print_error,
    print_wrapped,
    short_date,
    supports_color,
)

LS_USAGE = "usage: ls basetrades [sip|iex] [al]"
# the 'ls basetrades' feed words, the Alpaca feed of
# each; the free plan's sip is the delayed one
FEEDS = {"sip": "delayed_sip", "iex": "iex"}

ADD_USAGE = (
    "usage: add basetrade <stock>|all, or add "
    "basetrade <stock> price <price> count <count>"
)
# what a basetrade from the trades is
LOWEST = "lowest buy since the last sell"


class BaseTradeCommands(Commands):
    # a basetrade is the last buying price you keep for
    # a stock, one per stock (base_trades.csv); it
    # doesn't change the trades or totals
    name = "basetrade"
    plural = "basetrades"
    order = 50

    def ls(self, arg):
        """
        ls basetrades [sip|iex] [al]
            the basetrades in config order, with
            the current price of each stock and its
            change % from the buying price; sip
            takes the prices from the delayed_sip
            feed, iex from iex (default: config
            "feed"); with al, below it each
            alert's price per stock, a ! when the
            price is past it
        """
        args = arg.lower().split()
        feeds = [a for a in args if a in FEEDS]
        rest = [a for a in args if a not in FEEDS]
        if len(feeds) > 1 or rest not in ([], ["al"]):
            print_wrapped(LS_USAGE)
            return
        self._basetrades_show(
            alerts=bool(rest),
            feed=FEEDS[feeds[0]] if feeds else None,
        )

    def add(self, arg):
        """
        add basetrade <stock>|all
            take the basetrade of <stock> from its
            trades: the lowest buy since the last
            sell (a partial sell too), its price
            and count; of two equal buys the later
            one; with all, of each stock that has
            trades, after confirmation if older
            basetrades are replaced
        add basetrade <stock> price <price>
          count <count>
            save the last price you bought <stock>
            at and how many, e.g. 'add basetrade
            MRVU price 100 count 10'; replaces the
            stock's older basetrade
        """
        args = arg.split()
        if [a.lower() for a in args] == ["all"]:
            self._add_all()
            return
        values = parse_keywords(
            args[1:], ["price", "count"]
        )
        if not args or (args[1:] and values is None):
            print_wrapped(ADD_USAGE)
            return
        try:
            stock = parse_stock(args[0])
        except ValueError as e:
            print_error(f"error: {e}")
            return
        if values is None:
            self._add_lowest(stock)
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

    def _add_lowest(self, stock):
        try:
            buy = basetrades.from_trades(stock)
            replaced = basetrades.save(
                stock, buy["Price"], buy["Count"]
            )
        except basetrades.BaseTradeError as e:
            print_error(f"error: {e}")
            return
        print_wrapped(
            f"{'replaced' if replaced else 'added'} "
            f"basetrade of {stock.name}: "
            f"{buy['Count']} at {buy['Price']:g} "
            f"({LOWEST}, {short_date(buy['Date'])})"
        )

    def _add_all(self):
        # [(stock, lowest buy or None)] of the stocks
        # that have trades
        found = []
        for stock, _ in trades.summary():
            try:
                buy = basetrades.from_trades(stock)
            except basetrades.BaseTradeError:
                buy = None
            found.append((stock, buy))
        if not any(buy for _, buy in found):
            print_error(
                f"error: no stock has a {LOWEST}, "
                "see 'ls trades'"
            )
            return
        older = [
            stock.name
            for stock, buy in found
            if buy and basetrades.get(stock.name)
        ]
        if older:
            print_wrapped(
                "this replaces the basetrades of "
                f"{', '.join(older)}"
            )
            if not confirm("go on? [y/N] "):
                print_wrapped("cancelled")
                return
        print_wrapped(f"from the {LOWEST}:")
        for stock, buy in found:
            if buy is None:
                print_wrapped(
                    f"skipped {stock.name}: no buys "
                    "since the last sell"
                )
                continue
            replaced = basetrades.save(
                stock, buy["Price"], buy["Count"]
            )
            print_wrapped(
                f"{'replaced' if replaced else 'added'} "
                f"{stock.name}: {buy['Count']} at "
                f"{buy['Price']:g} "
                f"({short_date(buy['Date'])})"
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
                [*(s.name for s in Stock), "all"],
                keywords,
                [],
                keywords,
            ]
        if action == "rm":
            return [
                [b["Stock"] for b in basetrades.get_all()]
            ]
        if action == "ls":
            # al after a feed word
            if args and args[0].lower() in FEEDS:
                return [list(FEEDS), ["al"]]
            return [[*FEEDS, "al"]]
        return []

    def _basetrades_show(self, alerts=False, feed=None):
        found = basetrades.get_all()
        if not found:
            print_wrapped(
                "no basetrades yet, see 'help add "
                "basetrade'"
            )
            return
        prices = fetch_prices(feed)

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
        header = column_sep.join(header_cols)
        separator = rule(header)
        lines = [
            header,
            (
                f"{DIM}{separator}{RESET}"
                if color
                else separator
            ),
        ]
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
            lines.append(
                column_sep.join(
                    [name, qty, buy, price, change]
                )
            )
        print()
        print_table(lines)
        print()
        if alerts:
            print_basetrade_alerts(found, prices)
            print()

# base_trade_cmd: the bb (base buy) commands of the shell
#
#   bb add <stock> price <price> count <count>
#   bb ls, bb rm <stock>
#
# BaseTradeCommands implements add, ls and rm of base
# buys; the bb command (old_commands.py) calls them

from storage import (
    Stock,
    basetrade_delete,
    basetrade_set,
    basetrades_get_all,
)
from shell.interface import Commands
from shell.ui import (
    BOLD,
    COUNT_COLOR,
    DIM,
    PRICE_COLOR,
    RESET,
    TOTAL_STOCK_COLOR,
    WIDTH,
    XTOP_SEP,
    _confirm,
    _fetch_prices,
    _gain_color,
    _parse_stock,
    _print_error,
    _print_wrapped,
    _supports_color,
)


class BaseTradeCommands(Commands):
    # base buys are the last buying prices you keep, one
    # per stock (base_buy.csv); they don't change the
    # transactions or totals
    name = "basetrade"
    plural = "basetrades"
    order = 40

    def add(self, arg):
        """save the base buy of a stock"""
        self._basetrade_add(arg.split())

    def ls(self, arg):
        """the base buys with the current prices"""
        if arg.split():
            _print_wrapped("usage: bb ls")
            return
        self._basetrades_show()

    def rm(self, arg):
        """delete the base buy of a stock"""
        self._basetrade_rm(arg.split())

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
                [b["Stock"] for b in basetrades_get_all()]
            ]
        return []

    def _basetrade_add(self, args):
        usage = (
            "usage: bb add <stock> price <price> "
            "count <count>"
        )
        # the keywords say which number is which, so
        # their order doesn't matter
        if len(args) != 5:
            _print_wrapped(usage)
            return
        values = {
            args[1].lower(): args[2],
            args[3].lower(): args[4],
        }
        if set(values) != {"price", "count"}:
            _print_wrapped(usage)
            return
        try:
            stock = _parse_stock(args[0])
        except ValueError as e:
            _print_error(f"error: {e}")
            return
        try:
            price = float(values["price"])
            count = int(values["count"])
        except ValueError:
            _print_error(
                "error: price must be a number and "
                "count a whole number"
            )
            return
        if price <= 0 or count <= 0:
            _print_error(
                "error: price and count must be positive"
            )
            return
        replaced = basetrade_set(stock.name, price, count)
        _print_wrapped(
            f"{'replaced' if replaced else 'added'} "
            f"base buy of {stock.name}: {count} at "
            f"{price:g}"
        )

    def _basetrades_show(self):
        base_buys = basetrades_get_all()
        if not base_buys:
            _print_wrapped(
                "no base buys yet, add one with 'bb add "
                "<stock> price <price> count <count>'"
            )
            return
        prices = _fetch_prices()

        color = _supports_color()
        # laid out like the xtop table, the columns
        # widened to fill WIDTH
        column_sep = XTOP_SEP
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
        separator = "-" * WIDTH
        print()
        print(column_sep.join(header_cols))
        print(
            f"{DIM}{separator}{RESET}"
            if color
            else separator
        )
        for b in base_buys:
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
                    _gain_color(current - b["Price"])
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

    def _basetrade_rm(self, args):
        if len(args) != 1:
            _print_wrapped("usage: bb rm <stock>")
            return
        name = args[0].upper()
        found = next(
            (
                b
                for b in basetrades_get_all()
                if b["Stock"] == name
            ),
            None,
        )
        if found is None:
            _print_error(
                f"error: no base buy of {name}, "
                "see 'bb ls'"
            )
            return
        if not _confirm(
            f"delete base buy of {name}: "
            f"{found['Count']} at "
            f"{found['Price']:g}? [y/N] "
        ):
            _print_wrapped("cancelled")
            return
        basetrade_delete(name)
        _print_wrapped(f"deleted base buy of {name}")

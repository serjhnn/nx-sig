# base_trade_cmd: the bb (base buy) commands of the shell
#
#   bb add <stock> price <price> count <count>
#   bb ls, bb rm <stock>
#
# BaseTradeCmd is mixed into NxSigShell

from storage import (
    Stock,
    base_buy_delete,
    base_buy_set,
    base_buys_get_all,
)
from shell.ui import (
    BOLD,
    COUNT_COLOR,
    DIM,
    PRICE_COLOR,
    RESET,
    TOTAL_STOCK_COLOR,
    WIDTH,
    XTOP_SEP,
    _complete,
    _confirm,
    _fetch_prices,
    _gain_color,
    _parse_stock,
    _print_error,
    _print_wrapped,
    _supports_color,
)


class BaseTradeCmd:
    # ---------------- base buy ----------------
    # base buys are the last buying prices you keep, one
    # per stock (base_buy.csv); they don't change the
    # transactions or totals

    def do_bb(self, arg):
        """
        bb add <stock> price <price> count <count>
            save the base buy of <stock>: the last
            price you bought it at and how many,
            e.g. 'bb add MRVU price 100 count 10';
            replaces the stock's older base buy
        bb ls
            the base buys in config order, with
            the current price of each stock and its
            change % from the buying price
        bb rm <stock>
            delete the base buy of <stock>, after
            confirmation
        bb is short for base buy
        """
        args = arg.split()
        if not args:
            self.do_help("bb")
            return
        action, rest = args[0].lower(), args[1:]
        if action == "add":
            self._base_buy_add(rest)
        elif action == "ls":
            if rest:
                _print_wrapped("usage: bb ls")
                return
            self._base_buys_show()
        elif action == "rm":
            self._base_buy_rm(rest)
        else:
            _print_error(
                f"unknown action '{args[0]}' for bb, "
                "expected add/ls/rm"
            )

    def _base_buy_add(self, args):
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
        replaced = base_buy_set(stock.name, price, count)
        _print_wrapped(
            f"{'replaced' if replaced else 'added'} "
            f"base buy of {stock.name}: {count} at "
            f"{price:g}"
        )

    def _base_buys_show(self):
        base_buys = base_buys_get_all()
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

    def _base_buy_rm(self, args):
        if len(args) != 1:
            _print_wrapped("usage: bb rm <stock>")
            return
        name = args[0].upper()
        found = next(
            (
                b
                for b in base_buys_get_all()
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
        base_buy_delete(name)
        _print_wrapped(f"deleted base buy of {name}")

    def complete_bb(self, text, line, begidx, endidx):
        options = [["add", "ls", "rm"]]
        args = line.split()
        action = args[1].lower() if len(args) > 1 else ""
        if action == "add":
            keywords = ["price", "count"]
            options += [
                [s.name for s in Stock],
                keywords,
                [],
                keywords,
            ]
        elif action == "rm":
            options.append(
                [b["Stock"] for b in base_buys_get_all()]
            )
        return _complete(text, line, options)

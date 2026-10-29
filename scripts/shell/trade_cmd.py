# trade_cmd: the trades, your buys and sells
#
#   ls trades [<stock>]
#   add trade <stock> <buy|sell> count <count>
#       price <price>
#   add trade from <file>
#   rm trade <stock> <id>
#
# TradeCommands implements them for the verb commands
# of commands.py

import os

from engines import trades
from engines.trades import Stock, TradeType
from shell.interface import Commands
from shell.ui import (
    print_table,
    rule,
    BOLD,
    BUY_COLOR,
    COUNT_COLOR,
    DATE_COLOR,
    DIM,
    PRICE_COLOR,
    RESET,
    SELL_COLOR,
    TOTAL_COUNT_COLOR,
    TOTAL_STOCK_COLOR,
    column_separator,
    confirm,
    parse_id,
    parse_keywords,
    parse_stock,
    parse_trade_type,
    print_error,
    print_wrapped,
    short_date,
    supports_color,
)

ADD_USAGE = (
    "usage: add trade <stock> <buy|sell> count "
    "<count> price <price>"
)


class TradeCommands(Commands):
    name = "trade"
    plural = "trades"
    order = 20

    def ls(self, arg):
        """
        ls trades [<stock>]
            the trades of <stock> with their ids
            and its total; without a stock, the
            stocks that have trades
        """
        args = arg.split()
        if not args:
            self._stocks_with_trades()
            return
        if len(args) != 1:
            print_wrapped("usage: ls trades [<stock>]")
            return
        try:
            stock = parse_stock(args[0])
        except ValueError as e:
            print_error(f"error: {e}")
            return

        found = trades.get_all(stock)
        if not found:
            print_wrapped(f"no trades for {stock.name}")
            return

        color = supports_color()
        lines = _trades_header(color)
        lines += [_trade_row(t, color) for t in found]
        lines.append(lines[1])
        lines.append(_total_line(stock, color))
        print()
        print_table(lines)
        print()

    def add(self, arg):
        """
        add trade <stock> <buy|sell>
          count <count> price <price>
            record a trade, e.g. 'add trade SOXL
            buy count 10 price 20.5'
        add trade from <file>
            record the trades of a bank statement
            csv; fees, stocks not in the config and
            trades already recorded are left out
        """
        args = arg.split()
        if args and args[0].lower() == "from":
            self._add_from(arg.split(None, 1)[1:])
            return
        values = parse_keywords(
            args[2:], ["count", "price"]
        )
        if len(args) < 2 or values is None:
            print_wrapped(ADD_USAGE)
            return
        try:
            stock = parse_stock(args[0])
            trade_type = parse_trade_type(args[1])
        except ValueError as e:
            print_error(f"error: {e}")
            return
        try:
            count = int(values["count"])
            price = float(values["price"])
        except ValueError:
            print_error(
                "error: count must be a whole number and "
                "price a number"
            )
            return
        try:
            trades.add(stock, trade_type, count, price)
        except trades.TradeError as e:
            print_error(f"error: {e}")
            return
        print_wrapped(
            f"added {trade_type.name} {count} "
            f"{stock.name} @ {price:g}"
        )

    def _add_from(self, rest):
        """add trade from <file>, rest the words after
        from"""
        if not rest:
            print_wrapped("usage: add trade from <file>")
            return
        path = os.path.expanduser(rest[0].strip())
        try:
            added, skipped = trades.import_statement(path)
        except OSError as e:
            print_error(f"error: {e.strerror}: {path}")
            return
        except UnicodeDecodeError:
            print_error(f"error: not a text file: {path}")
            return

        name = os.path.basename(path)
        if added:
            print_wrapped(
                f"added {len(added)} trades from {name}:"
            )
            for t in added:
                date = short_date(t["Date"])
                print_wrapped(
                    f"  {t['Stock']} {t['Type'].name} "
                    f"{t['Count']} @ {t['Price']:g}, "
                    f"{date} {t['Time']}"
                )
        else:
            print_wrapped(f"no trades added from {name}")
        if skipped:
            print_wrapped(f"skipped {len(skipped)}:")
            for reason in skipped:
                print_wrapped(f"  {reason}")

    def rm(self, arg):
        """
        rm trade <stock> <id>
            delete a trade after confirmation, the
            stock's total is recalculated; the ids
            are in 'ls trades <stock>'
        """
        args = arg.split()
        trade_id = (
            parse_id(args[1]) if len(args) == 2 else None
        )
        if trade_id is None:
            print_wrapped("usage: rm trade <stock> <id>")
            return
        try:
            stock = parse_stock(args[0])
        except ValueError as e:
            print_error(f"error: {e}")
            return
        trade = trades.get(stock, trade_id)
        if trade is None:
            print_error(
                f"error: no {stock.name} trade {trade_id}, "
                f"see 'ls trades {stock.name}'"
            )
            return

        color = supports_color()
        print()
        print_table(
            _trades_header(color)
            + [_trade_row(trade, color)]
        )
        print()
        if not confirm(
            f"delete {stock.name} trade {trade_id}? [y/N] "
        ):
            print_wrapped("cancelled")
            return
        trades.delete(stock, trade_id)
        print_wrapped(
            f"deleted {stock.name} trade {trade_id}"
        )

    def complete(self, action, args):
        stocks = [s.name for s in Stock]
        if action == "add":
            keywords = ["count", "price"]
            types = [t.name.lower() for t in TradeType]
            if args[:1] == ["from"]:
                return [["from"]]
            return [
                stocks + ["from"],
                types,
                keywords,
                [],
                keywords,
            ]
        if action == "rm":
            return [stocks, _trade_ids(args[:1])]
        return [stocks]

    def _stocks_with_trades(self):
        """the stocks that have trades: how many and the
        date of the last one"""
        rows = trades.summary()
        if not rows:
            print_wrapped(
                "no trades yet, see 'help add trade'"
            )
            return
        color = supports_color()
        column_sep = column_separator(color, 3)
        header_cols = [
            f"{'Name':<5}",
            f"{'Trades':>6}",
            f"{'Last trade':<14}",
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
        for stock, found in rows:
            last = found[-1]
            date = short_date(last["Date"])
            when = f"{date} {last['Time']}"
            cols = [
                f"{stock.name:<5}",
                f"{len(found):>6}",
                f"{when:<14}",
            ]
            if color:
                cols = [
                    f"{BOLD}{TOTAL_STOCK_COLOR}"
                    f"{cols[0]}{RESET}",
                    f"{COUNT_COLOR}{cols[1]}{RESET}",
                    f"{DATE_COLOR}{cols[2]}{RESET}",
                ]
            lines.append(column_sep.join(cols))
        print()
        print_table(lines)
        print()


def _trade_ids(args):
    """the trade ids of the stock named in args, for
    completion"""
    try:
        stock = parse_stock(args[0]) if args else None
    except ValueError:
        stock = None
    if stock is None:
        return []
    return [str(t["Id"]) for t in trades.get_all(stock)]


def _trades_header(color):
    """the column names of the trades table and the
    separator line under them"""
    header_cols = [
        f"{'Id':>4}",
        f"{'Date':>8}",
        f"{'Time':>5}",
        f"{'Type':>4}",
        f"{'Count':>5}",
        f"{'Price':<7}",
    ]
    if color:
        header_cols = [
            f"{DIM}{col}{RESET}" for col in header_cols
        ]
    header = column_separator(color, 6).join(header_cols)
    separator = rule(header)
    return [
        header,
        f"{DIM}{separator}{RESET}" if color else separator,
    ]


def _trade_row(t, color):
    """one trade as a row of the trades table"""
    trade_type = t['Type'].name
    if color:
        type_color = (
            BUY_COLOR if trade_type == "BUY" else SELL_COLOR
        )
        trade_type = f"{type_color}{trade_type:>4}{RESET}"
        day = short_date(t['Date'])
        date = f"{DATE_COLOR}{day:>8}{RESET}"
        time = f"{DIM}{t['Time']:>5}{RESET}"
        count = f"{COUNT_COLOR}{t['Count']:>5}{RESET}"
        price = f"{PRICE_COLOR}{t['Price']:<7.2f}{RESET}"
        trade_id = f"{DIM}{t['Id']:>4}{RESET}"
    else:
        trade_id = f"{t['Id']:>4}"
        trade_type = f"{trade_type:>4}"
        date = f"{short_date(t['Date']):>8}"
        time = f"{t['Time']:>5}"
        count = f"{t['Count']:>5}"
        price = f"{t['Price']:<7.2f}"
    return column_separator(color, 6).join(
        [
            trade_id,
            date,
            time,
            trade_type,
            count,
            price,
        ]
    )


def _total_line(stock, color):
    """the stock's total count, average buy price and
    position sum"""
    total_count, avg_price = trades.total(stock)
    total_sum = total_count * avg_price
    if color:
        total_line = (
            f"{DIM}total:{RESET} "
            f"{BOLD}{TOTAL_COUNT_COLOR}"
            f"{total_count}{RESET} "
            f"{BOLD}{TOTAL_STOCK_COLOR}{stock.name}{RESET}"
            f"{DIM}, avg buy{RESET} "
            f"{BOLD}{PRICE_COLOR}{avg_price:.2f}{RESET}"
            f"{DIM}, sum{RESET} "
            f"{BOLD}{PRICE_COLOR}{total_sum:.2f}{RESET}"
        )
    else:
        total_line = (
            f"total: {total_count} {stock.name}, avg buy "
            f"{avg_price:.2f}, sum {total_sum:.2f}"
        )
    return total_line

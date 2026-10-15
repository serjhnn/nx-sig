# trade_cmd: the trades, your buys and sells
#
#   ls trades [<stock>]
#   add trade <stock> <buy|sell> count <count>
#       price <price>
#   rm trade <stock> <id>
#
# TradeCommands implements them for the verb commands
# of commands.py

from storage import (
    Stock,
    TradeType,
    trade_add,
    trade_delete,
    trades_get_all,
    trades_total_get,
)
from shell.interface import Commands
from shell.ui import (
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
    WIDTH,
    _column_sep,
    _confirm,
    _parse_id,
    _parse_keywords,
    _parse_stock,
    _parse_trade_type,
    _print_error,
    _print_wrapped,
    _short_date,
    _supports_color,
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
            _print_wrapped("usage: ls trades [<stock>]")
            return
        try:
            stock = _parse_stock(args[0])
        except ValueError as e:
            _print_error(f"error: {e}")
            return

        trades = trades_get_all(stock)
        if not trades:
            _print_wrapped(f"no trades for {stock.name}")
            return

        color = _supports_color()
        print()
        _print_trades_header(color)
        for t in trades:
            _print_trade_row(t, color)
        separator = "-" * WIDTH
        print(
            f"{DIM}{separator}{RESET}"
            if color
            else separator
        )
        _print_total(stock, color)
        print()

    def add(self, arg):
        """
        add trade <stock> <buy|sell>
          count <count> price <price>
            record a trade, e.g. 'add trade SOXL
            buy count 10 price 20.5'
        """
        args = arg.split()
        values = _parse_keywords(
            args[2:], ["count", "price"]
        )
        if len(args) < 2 or values is None:
            _print_wrapped(ADD_USAGE)
            return
        try:
            stock = _parse_stock(args[0])
            trade_type = _parse_trade_type(args[1])
        except ValueError as e:
            _print_error(f"error: {e}")
            return
        try:
            count = int(values["count"])
            price = float(values["price"])
        except ValueError:
            _print_error(
                "error: count must be a whole number and "
                "price a number"
            )
            return
        if count <= 0 or price <= 0:
            _print_error(
                "error: count and price must be positive"
            )
            return

        trade_add(stock, trade_type, count, price)
        _print_wrapped(
            f"added {trade_type.name} {count} "
            f"{stock.name} @ {price:g}"
        )

    def rm(self, arg):
        """
        rm trade <stock> <id>
            delete a trade after confirmation, the
            stock's total is recalculated; the ids
            are in 'ls trades <stock>'
        """
        args = arg.split()
        trade_id = (
            _parse_id(args[1]) if len(args) == 2 else None
        )
        if trade_id is None:
            _print_wrapped("usage: rm trade <stock> <id>")
            return
        try:
            stock = _parse_stock(args[0])
        except ValueError as e:
            _print_error(f"error: {e}")
            return
        trade = next(
            (
                t
                for t in trades_get_all(stock)
                if t["Id"] == trade_id
            ),
            None,
        )
        if trade is None:
            _print_error(
                f"error: no {stock.name} trade {trade_id}, "
                f"see 'ls trades {stock.name}'"
            )
            return

        color = _supports_color()
        print()
        _print_trades_header(color)
        _print_trade_row(trade, color)
        print()
        if not _confirm(
            f"delete {stock.name} trade {trade_id}? [y/N] "
        ):
            _print_wrapped("cancelled")
            return
        trade_delete(stock, trade_id)
        _print_wrapped(
            f"deleted {stock.name} trade {trade_id}"
        )

    def complete(self, action, args):
        stocks = [s.name for s in Stock]
        if action == "add":
            keywords = ["count", "price"]
            types = [t.name.lower() for t in TradeType]
            return [stocks, types, keywords, [], keywords]
        if action == "rm":
            return [stocks, _trade_ids(args[:1])]
        return [stocks]

    def _stocks_with_trades(self):
        """the stocks that have trades: how many and the
        date of the last one"""
        rows = []
        for stock in Stock:
            trades = trades_get_all(stock)
            if trades:
                rows.append((stock, trades))
        if not rows:
            _print_wrapped(
                "no trades yet, see 'help add trade'"
            )
            return
        color = _supports_color()
        column_sep = _column_sep(color)
        header_cols = [
            f"{'Name':<5}",
            f"{'Trades':>6}",
            f"{'Last trade':<14}",
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
        for stock, trades in rows:
            last = trades[-1]
            when = f"{_short_date(last['Date'])} {last['Time']}"
            cols = [
                f"{stock.name:<5}",
                f"{len(trades):>6}",
                f"{when:<14}",
            ]
            if color:
                cols = [
                    f"{BOLD}{TOTAL_STOCK_COLOR}"
                    f"{cols[0]}{RESET}",
                    f"{COUNT_COLOR}{cols[1]}{RESET}",
                    f"{DATE_COLOR}{cols[2]}{RESET}",
                ]
            print(column_sep.join(cols))
        print()


def _trade_ids(args):
    """the trade ids of the stock named in args, for
    completion"""
    try:
        stock = _parse_stock(args[0]) if args else None
    except ValueError:
        stock = None
    if stock is None:
        return []
    return [str(t["Id"]) for t in trades_get_all(stock)]


def _print_trades_header(color):
    """print the column names of the trades table and a
    separator line"""
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
    print(_column_sep(color).join(header_cols))
    separator = "-" * WIDTH
    print(
        f"{DIM}{separator}{RESET}" if color else separator
    )


def _print_trade_row(t, color):
    """print one trade as a row of the trades table"""
    trade_type = t['Type'].name
    if color:
        type_color = (
            BUY_COLOR if trade_type == "BUY" else SELL_COLOR
        )
        trade_type = f"{type_color}{trade_type:>4}{RESET}"
        short_date = _short_date(t['Date'])
        date = f"{DATE_COLOR}{short_date:>8}{RESET}"
        time = f"{DIM}{t['Time']:>5}{RESET}"
        count = f"{COUNT_COLOR}{t['Count']:>5}{RESET}"
        price = f"{PRICE_COLOR}{t['Price']:<7.2f}{RESET}"
        trade_id = f"{DIM}{t['Id']:>4}{RESET}"
    else:
        trade_id = f"{t['Id']:>4}"
        trade_type = f"{trade_type:>4}"
        date = f"{_short_date(t['Date']):>8}"
        time = f"{t['Time']:>5}"
        count = f"{t['Count']:>5}"
        price = f"{t['Price']:<7.2f}"
    print(
        _column_sep(color).join(
            [
                trade_id,
                date,
                time,
                trade_type,
                count,
                price,
            ]
        )
    )


def _print_total(stock, color):
    """print the stock's total count, average buy price and
    position sum"""
    total_count, avg_price = trades_total_get(stock)
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
    print(total_line)

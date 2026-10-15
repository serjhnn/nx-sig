# trade_cmd: the tr (transactions) commands of the shell
#
#   tr add <stock> <buy|sell> <count> <price>
#   tr get <stock>, tr del-last <stock>
#
# TradeCommands implements add, ls and rm of trades;
# the tr and 'ls <stock>' commands (old_commands.py)
# call them

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
    _parse_stock,
    _parse_trade_type,
    _print_error,
    _print_wrapped,
    _short_date,
    _supports_color,
)


class TradeCommands(Commands):
    name = "trade"
    plural = "trades"
    order = 20

    def add(self, arg):
        """record a transaction"""
        self._trade_add(arg.split())

    def ls(self, arg):
        """the transactions and total of a stock"""
        self._trades_show(arg.split())

    def rm(self, arg):
        """delete the last transaction of a stock"""
        self._trade_delete_last(arg.split())

    def complete(self, action, args):
        options = [[s.name for s in Stock]]
        # only 'add' takes a transaction type after the
        # stock name
        if action == "add":
            options.append(
                [t.name.lower() for t in TradeType]
            )
        return options

    def _trade_add(self, args):
        if len(args) != 4:
            _print_wrapped(
                "usage: tr add <stock> <buy|sell> <count> "
                "<price>"
            )
            return
        try:
            stock = _parse_stock(args[0])
            trade_type = _parse_trade_type(args[1])
            count = int(args[2])
            price = float(args[3])
        except ValueError as e:
            _print_error(f"error: {e}")
            return
        if count <= 0 or price <= 0:
            _print_error(
                "error: count and price must be positive"
            )
            return

        trade_add(stock, trade_type, count, price)
        _print_wrapped(
            f"added {trade_type.name} {count} "
            f"{stock.name} @ {price}"
        )

    def _trade_delete(self, args):
        if len(args) != 2:
            _print_wrapped("usage: tr del <stock> <index>")
            return
        try:
            stock = _parse_stock(args[0])
        except ValueError as e:
            _print_error(f"error: {e}")
            return
        if not args[1].isdigit():
            _print_error(
                "error: index must be a number, got "
                f"'{args[1]}'"
            )
            return
        index = int(args[1])

        transaction = next(
            (
                t
                for t in trades_get_all(stock)
                if t["Id"] == index
            ),
            None,
        )
        if transaction is None:
            _print_error(
                f"error: no {stock.name} transaction with "
                f"Id {index}"
            )
            return
        self._confirm_and_delete(stock, transaction)

    def _trade_delete_last(self, args):
        if len(args) != 1:
            _print_wrapped("usage: tr del-last <stock>")
            return
        try:
            stock = _parse_stock(args[0])
        except ValueError as e:
            _print_error(f"error: {e}")
            return

        transactions = trades_get_all(stock)
        if not transactions:
            _print_wrapped(
                f"no transactions for {stock.name}"
            )
            return
        # transactions are appended, so the last row is the
        # latest one
        self._confirm_and_delete(stock, transactions[-1])

    def _confirm_and_delete(self, stock, transaction):
        """show a transaction, ask for confirmation and
        delete it"""
        index = transaction["Id"]
        color = _supports_color()
        print()
        _print_trades_header(color)
        _print_trade_row(transaction, color)
        print()
        if not _confirm(
            f"delete this {stock.name} transaction? "
            "[y/N] "
        ):
            _print_wrapped("cancelled")
            return

        trade_delete(stock, index)
        _print_wrapped(
            f"deleted {stock.name} transaction {index}"
        )

    def _trades_show(self, args):
        if len(args) != 1:
            _print_wrapped("usage: tr get <stock>")
            return
        try:
            stock = _parse_stock(args[0])
        except ValueError as e:
            _print_error(f"error: {e}")
            return

        transactions = trades_get_all(stock)
        if not transactions:
            _print_wrapped(
                f"no transactions for {stock.name}"
            )
            return

        color = _supports_color()
        print()
        _print_trades_header(color)
        for t in transactions:
            _print_trade_row(t, color)
        separator = "-" * WIDTH

        print(
            f"{DIM}{separator}{RESET}"
            if color
            else separator
        )
        _print_total(stock, color)
        print()


def _print_trades_header(color):
    """print the column names of the transactions table and
    a separator line"""
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
    """print one transaction as a row of the transactions
    table"""
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
        index = f"{DIM}{t['Id']:>4}{RESET}"
    else:
        index = f"{t['Id']:>4}"
        trade_type = f"{trade_type:>4}"
        date = f"{_short_date(t['Date']):>8}"
        time = f"{t['Time']:>5}"
        count = f"{t['Count']:>5}"
        price = f"{t['Price']:<7.2f}"
    print(
        _column_sep(color).join(
            [
                index,
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

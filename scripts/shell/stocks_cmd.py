# stocks_cmd: the held stocks, 'ls' without arguments
#
# StocksCommands implements ls of the held stocks; 'ls'
# (old_commands.py) calls it

from shell.interface import Commands
from shell.ui import (
    BOLD,
    COUNT_COLOR,
    DIM,
    PRICE_COLOR,
    RESET,
    TOTAL_STOCK_COLOR,
    WIDTH,
    _column_sep,
    _fetch_prices,
    _gain_color,
    _held_positions,
    _print_wrapped,
    _supports_color,
)


class StocksCommands(Commands):
    name = "stocks"
    plural = "stocks"
    order = 10

    def ls(self, arg):
        """count, average price, total and growth % of
        the held stocks"""
        self._totals_all()

    def _totals_all(self):
        totals = _held_positions()
        if not totals:
            _print_wrapped("no stocks held")
            return
        prices = _fetch_prices()

        color = _supports_color()
        column_sep = _column_sep(color)
        header_cols = [
            f"{'Name':<5}",
            f"{'Count':>5}",
            f"{'Avg Price':>9}",
            f"{'Total':>8}",
            f"{'Growth %':>8}",
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
        for stock, total_count, avg_price in totals:
            name = f"{stock.name:<5}"
            count = f"{total_count:>5}"
            avg = f"{avg_price:>9.2f}"
            total = f"{total_count * avg_price:>8.2f}"
            growth = f"{'-':>8}"
            growth_color = DIM
            current = prices.get(stock.name)
            if current is not None and avg_price > 0:
                pct = (
                    (current - avg_price) / avg_price * 100
                )
                growth = f"{pct:>+7.2f}%"
                growth_color = _gain_color(pct)
            if color:
                name = (
                    f"{BOLD}{TOTAL_STOCK_COLOR}"
                    f"{name}{RESET}"
                )
                count = f"{COUNT_COLOR}{count}{RESET}"
                avg = f"{PRICE_COLOR}{avg}{RESET}"
                total = f"{PRICE_COLOR}{total}{RESET}"
                growth = f"{growth_color}{growth}{RESET}"
            print(
                column_sep.join(
                    [name, count, avg, total, growth]
                )
            )
        print()

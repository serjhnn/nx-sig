# stocks_cmd: the stocks you hold
#
#   ls stocks
#
# StocksCommands implements it for the verb commands of
# commands.py

from shell.interface import Commands
from shell.ui import (
    BOLD,
    COUNT_COLOR,
    DIM,
    PRICE_COLOR,
    RESET,
    TOTAL_STOCK_COLOR,
    WIDTH,
    column_separator,
    fetch_prices,
    color_for_gain,
    held_positions,
    parse_stock,
    print_wrapped,
    supports_color,
)


class StocksCommands(Commands):
    name = "stocks"
    plural = "stocks"
    order = 10

    def ls(self, arg):
        """
        ls stocks
            count, average buy price and total of
            the stocks you hold, and growth %: how
            far the current price is above (or
            below) the average price
        """
        args = arg.split()
        if args:
            try:
                stock = parse_stock(args[0])
            except ValueError:
                stock = None
            # one stock's details are its trades
            if len(args) == 1 and stock:
                print_wrapped(
                    f"use 'ls trades {stock.name}'"
                )
            else:
                print_wrapped("usage: ls stocks")
            return
        self._totals_all()

    def _totals_all(self):
        totals = held_positions()
        if not totals:
            print_wrapped("no stocks held")
            return
        prices = fetch_prices()

        color = supports_color()
        column_sep = column_separator(color)
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
                growth_color = color_for_gain(pct)
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

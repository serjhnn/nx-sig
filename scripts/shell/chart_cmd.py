# chart_cmd: the price of a stock over a period
#
#   chart <stock> [period <n> <days|weeks|months>]
#
# the chart comes from chart.stock_chart (the prices,
# the average buy price and the trades); this file
# reads the command and prints it.
#
# ChartCmd is mixed into NxSigShell: a command of its
# own, not a kind of data

import requests

import chart
from shell.ui import (
    BOLD,
    BUY_COLOR,
    DIM,
    PRICE_COLOR,
    RESET,
    SELL_COLOR,
    TOTAL_STOCK_COLOR,
    complete_options,
    parse_stock,
    print_error,
    print_wrapped,
    stock_names,
    supports_color,
    width,
)

USAGE = (
    "usage: chart <stock> [period <n> "
    "<days|weeks|months>]"
)


class ChartCmd:
    def do_chart(self, arg):
        """
        chart <stock> [period <n> <unit>]
            the price of <stock> over the period
            (5 days by default) as a chart, one *
            per price, with your average buy
            price as a . line and your trades as
            B / S; <unit> is days, weeks or
            months, e.g. 'chart TSMX period 3
            months'
        """
        args = arg.split()
        if not args:
            print_wrapped(USAGE)
            return
        try:
            stock = parse_stock(args[0])
            period = chart.parse_period(args[1:])
        except ValueError as e:
            print_error(f"error: {e}")
            return
        colors = _colors() if supports_color() else None
        try:
            lines = chart.stock_chart(
                stock, period, width(), colors
            )
        except KeyError as e:
            print_error(
                f"error: missing {e.args[0]} in .env, "
                "can't get the prices"
            )
            return
        except (requests.RequestException, ValueError) as e:
            print_error(f"error: can't get the prices: {e}")
            return
        if not lines:
            print_wrapped(
                f"no prices for {stock.name} in the last "
                f"{period[1]}"
            )
            return
        print()
        print("\n".join(lines))
        print()

    def complete_chart(self, text, line, begidx, endidx):
        return complete_options(
            text,
            line,
            [
                stock_names(),
                ["period"],
                [],
                ["days", "weeks", "months"],
            ],
        )


def _colors():
    return {
        "*": PRICE_COLOR,
        "B": f"{BOLD}{BUY_COLOR}",
        "S": f"{BOLD}{SELL_COLOR}",
        ".": DIM,
        "dim": DIM,
        "title": f"{BOLD}{TOTAL_STOCK_COLOR}",
        "reset": RESET,
    }

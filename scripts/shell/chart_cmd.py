# chart_cmd: the price of a stock over a period
#
#   chart <stock> [period <n> <days|weeks|months>]
#
# the bars come from trade_engine.get_bars, the drawing
# from chart.py; the average buy price and the trades
# in the period come from storage.
#
# ChartCmd is mixed into NxSigShell: a command of its
# own, not a kind of data

from datetime import datetime

import requests

import chart
import trade_engine
from storage import Stock, trades_get_all, trades_total_get
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
        days, text = period
        tf, _ = chart.timeframe(days)
        try:
            bars = trade_engine.get_bars(
                stock.name, days, tf
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
        if not bars:
            print_wrapped(
                f"no prices for {stock.name} in the last "
                f"{text}"
            )
            return
        count, avg = trades_total_get(stock)
        lines = chart.chart_lines(
            stock.name,
            period,
            bars,
            width(),
            avg=avg if count > 0 else None,
            trades=_trades(stock),
            colors=_colors() if supports_color() else None,
        )
        print()
        print("\n".join(lines))
        print()

    def complete_chart(self, text, line, begidx, endidx):
        return complete_options(
            text,
            line,
            [
                [s.name for s in Stock],
                ["period"],
                [],
                ["days", "weeks", "months"],
            ],
        )


def _trades(stock):
    """[(time, 'B' or 'S', price)] of the stock's
    trades"""
    trades = []
    for t in trades_get_all(stock):
        try:
            when = datetime.strptime(
                f"{t['Date']} {t['Time']}", "%d.%m.%Y %H:%M"
            )
        except ValueError:
            continue
        side = "B" if t["Type"].name == "BUY" else "S"
        trades.append((when, side, t["Price"]))
    return trades


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

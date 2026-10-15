# ui: the look of the shell and the helpers every
# command module shares
#
# WIDTH, the colors (the logo gradient, PRICE_COLOR,
# DIM, ...), printing within WIDTH, the y/N question,
# the argument parsers, tab completion and the current
# prices
#
# shared helpers:
#   _supports_color(), _column_sep(color)
#   _print_dim(text), _print_wrapped(text),
#   _print_error(text), _wrap(text)
#   _confirm(question)  True if answered y/yes
#   _parse_stock(name), _parse_id(text),
#   _parse_direction(name), _parse_transaction_type(name)
#   _short_date(value)
#   _complete(text, line, options_per_position)
#   _fetch_prices(), _held_positions(), _gain_color(gain)

import os
import sys
import textwrap

from storage import (
    Stock,
    TransactionType,
    transactions_total_get,
)
from trade_engine import get_latest_prices

# all output is kept within the width of the 'tr get' table
# so it fits a mobile screen
WIDTH = 48

# 256-color gradient, one per logo line, top to bottom:
# light blue -> dark green
LOGO_COLORS = [
    f"\033[38;5;{c}m" for c in (117, 80, 43, 36, 29, 22)
]
DIM = "\033[2m"
DATE_COLOR = "\033[38;5;30m"
COUNT_COLOR = "\033[38;5;96m"
TOTAL_COUNT_COLOR = "\033[38;5;28m"
PRICE_COLOR = "\033[38;5;136m"
TOTAL_STOCK_COLOR = "\033[38;5;117m"
BUY_COLOR = "\033[38;5;28m"
SELL_COLOR = "\033[38;5;124m"
BOLD = "\033[1m"
RESET = "\033[0m"
PROMPT_COLOR = LOGO_COLORS[2]  # teal from the logo gradient
RULE_COLOR = LOGO_COLORS[
    -1
]  # dark green, the last color of the logo gradient


def _supports_color():
    if not sys.stdout.isatty() or os.environ.get(
        "NO_COLOR"
    ):
        return False
    if os.name == "nt":
        # enables ANSI escape codes in the Windows console
        os.system("")
    return True


def _column_sep(color):
    return f"{DIM} | {RESET}" if color else " | "


def _print_dim(text):
    print(
        f"{DIM}{text}{RESET}" if _supports_color() else text
    )


def _print_wrapped(text):
    """print plain text wrapped to WIDTH, dimmed"""
    _print_dim(_wrap(text))


def _print_error(text):
    """print an error wrapped to WIDTH, not dimmed so it
    stands out"""
    print(_wrap(text))


def _wrap(text):
    return textwrap.fill(
        text,
        WIDTH,
        subsequent_indent="  ",
        break_on_hyphens=False,
    )


def _confirm(question):
    """ask a y/N question, True if answered y or yes"""
    try:
        answer = input(question)
    except (EOFError, KeyboardInterrupt):
        # Ctrl+D / Ctrl+C at the prompt cancels instead
        # of leaving the shell
        answer = ""
        print()
    return answer.strip().lower() in ("y", "yes")


def _parse_stock(name):
    try:
        return Stock[name.upper()]
    except KeyError:
        raise ValueError(
            f"unknown stock '{name}', expected one of: "
            f"{', '.join(s.name for s in Stock)}"
        )


def _short_date(value):
    """Display stored dd.mm.yyyy dates as dd.mm.yy."""
    return (
        f"{value[:6]}{value[-2:]}"
        if len(value) == 10
        else value
    )


def _parse_id(text):
    """a positive whole number, or None"""
    if text.isdigit() and int(text) > 0:
        return int(text)
    return None


def _parse_direction(name):
    if name.lower() not in ("down", "up"):
        raise ValueError(
            f"unknown direction '{name}', expected down/up"
        )
    return name.lower()


def _parse_transaction_type(name):
    try:
        return TransactionType[name.upper()]
    except KeyError:
        raise ValueError(
            f"unknown transaction type '{name}', expected "
            "buy/sell"
        )


def _complete(text, line, options_per_position):
    """complete the argument at the current position from
    options_per_position"""
    position = len(line.split()) - (1 if text else 0) - 1
    if 0 <= position < len(options_per_position):
        return [
            o
            for o in options_per_position[position]
            if o.lower().startswith(text.lower())
        ]
    return []


def _fetch_prices():
    """{stock: current price} from the API, or {} after
    printing why the prices could not be fetched"""
    try:
        return get_latest_prices()
    except KeyError as e:
        _print_error(
            f"error: missing {e.args[0]} in .env, "
            "can't get current prices"
        )
    except Exception as e:  # network or API errors
        _print_error(
            f"error: can't get current prices: {e}"
        )
    return {}


def _held_positions():
    """(stock, count, average buy price) of every stock
    whose count is not 0"""
    positions = [
        (stock, *transactions_total_get(stock))
        for stock in Stock
    ]
    return [p for p in positions if p[1] != 0]


def _gain_color(gain):
    if gain > 0:
        return BUY_COLOR
    if gain < 0:
        return SELL_COLOR
    return DIM


XTOP_SEP = " "

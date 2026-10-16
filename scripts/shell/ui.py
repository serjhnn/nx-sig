# ui: the look of the shell and the helpers every
# command module shares
#
# WIDTH, the colors (the logo gradient, PRICE_COLOR,
# DIM, ...), printing within WIDTH, the y/N question,
# the argument parsers, tab completion and the current
# prices
#
# shared helpers:
#   supports_color(), column_separator(color)
#   print_dim(text), print_wrapped(text),
#   print_error(text)
#   confirm(question)  True if answered y/yes
#   parse_stock(name), parse_id(text),
#   parse_direction(name), parse_trade_type(name)
#   parse_keywords(args, keywords)
#                       {keyword: value} of 'count 10 ...'
#   short_date(value)
#   complete_options(text, line, options_per_position)
#   fetch_prices(), held_positions(), color_for_gain(gain)

import os
import sys
import textwrap

from storage import (
    Stock,
    TradeType,
    trades_total_get,
)
from trade_engine import get_latest_prices

# all output is kept within the width of the
# 'ls trades <stock>' table so it fits a mobile screen
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


def supports_color():
    if not sys.stdout.isatty() or os.environ.get(
        "NO_COLOR"
    ):
        return False
    if os.name == "nt":
        # enables ANSI escape codes in the Windows console
        os.system("")
    return True


def column_separator(color):
    return f"{DIM} | {RESET}" if color else " | "


def print_dim(text):
    print(
        f"{DIM}{text}{RESET}" if supports_color() else text
    )


def print_wrapped(text):
    """print plain text wrapped to WIDTH, dimmed"""
    print_dim(_wrap(text))


def print_error(text):
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


def confirm(question):
    """ask a y/N question, True if answered y or yes"""
    try:
        answer = input(question)
    except (EOFError, KeyboardInterrupt):
        # Ctrl+D / Ctrl+C at the prompt cancels instead
        # of leaving the shell
        answer = ""
        print()
    return answer.strip().lower() in ("y", "yes")


def parse_stock(name):
    try:
        return Stock[name.upper()]
    except KeyError:
        raise ValueError(
            f"unknown stock '{name}', expected one of: "
            f"{', '.join(s.name for s in Stock)}"
        )


def short_date(value):
    """Display stored dd.mm.yyyy dates as dd.mm.yy."""
    return (
        f"{value[:6]}{value[-2:]}"
        if len(value) == 10
        else value
    )


def parse_id(text):
    """a positive whole number, or None"""
    if text.isdigit() and int(text) > 0:
        return int(text)
    return None


def parse_direction(name):
    if name.lower() not in ("down", "up"):
        raise ValueError(
            f"unknown direction '{name}', expected down/up"
        )
    return name.lower()


def parse_trade_type(name):
    try:
        return TradeType[name.upper()]
    except KeyError:
        raise ValueError(
            f"unknown trade type '{name}', expected "
            "buy/sell"
        )


def parse_keywords(args, keywords):
    """{keyword: value} of words like 'count 10 price
    20', the keywords in any order; None unless each of
    keywords comes once with a value"""
    if len(args) != 2 * len(keywords):
        return None
    values = {
        key.lower(): value
        for key, value in zip(args[::2], args[1::2])
    }
    if set(values) != set(keywords):
        return None
    return values


def complete_options(text, line, options_per_position):
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


def fetch_prices():
    """{stock: current price} from the API, or {} after
    printing why the prices could not be fetched"""
    try:
        return get_latest_prices()
    except KeyError as e:
        print_error(
            f"error: missing {e.args[0]} in .env, "
            "can't get current prices"
        )
    except Exception as e:  # network or API errors
        print_error(f"error: can't get current prices: {e}")
    return {}


def held_positions():
    """(stock, count, average buy price) of every stock
    whose count is not 0"""
    positions = [
        (stock, *trades_total_get(stock)) for stock in Stock
    ]
    return [p for p in positions if p[1] != 0]


def color_for_gain(gain):
    if gain > 0:
        return BUY_COLOR
    if gain < 0:
        return SELL_COLOR
    return DIM


XTOP_SEP = " "

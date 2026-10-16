# ui: the look of the shell and the helpers every
# command module shares
#
# width(), the colors (the logo gradient, PRICE_COLOR,
# DIM, ...), printing within the width, the y/N
# question, the argument parsers, tab completion and the
# current prices
#
# the width is config.json "width" (or NX_WIDTH in .env,
# for one device): a number, or "auto" for the
# terminal's width. the tables are made for
# DEFAULT_WIDTH; on a wider screen the gaps between
# their columns grow, by at most MAX_GAP_GROWTH each.
# the theme is config.json "theme" (or NX_THEME in
# .env): colored, or plain for no colors. 'terminal set'
# writes NX_WIDTH / NX_THEME.
#
# shared helpers:
#   width()            the output width now
#   width_setting(), theme_setting()
#                      (setting, where it comes from)
#   theme()            colored or plain
#   setting_problems() lines about settings that are
#                      not used as they are
#   supports_color()
#   column_separator(color, columns=None)
#                      ' | ' between the columns
#   space_separator(columns, base)
#                      spaces between the columns
#   print_dim(text), print_wrapped(text),
#   print_error(text)
#   confirm(question)  True if answered y/yes
#   stock_names()      the config "indices"
#   parse_stock(name), parse_id(text),
#   parse_direction(name), parse_trade_type(name)
#   parse_keywords(args, keywords)
#                       {keyword: value} of 'count 10 ...'
#   short_date(value)
#   complete_options(text, line, options_per_position)
#   fetch_prices(), held_positions(), color_for_gain(gain)

import os
import shutil
import sys
import textwrap

from storage import (
    Stock,
    TradeType,
    config,
    trades_total_get,
)
from trade_engine import get_latest_prices

# the width the tables are made for, the width of the
# 'ls trades <stock>' table, so it fits a phone screen;
# it is also the narrowest: the xtop table has only one
# space between its columns
DEFAULT_WIDTH = 48
MIN_WIDTH = DEFAULT_WIDTH
# so a table on a wide screen isn't spread thin
MAX_GAP_GROWTH = 4
THEMES = ("colored", "plain")
DEFAULT_THEME = "colored"

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


def _setting(env_name, key, default):
    """(setting, where it comes from): NX_... in .env
    for this device, config.json for all of them, or the
    default"""
    if os.environ.get(env_name):
        return os.environ[env_name], f"{env_name} in .env"
    if key in config:
        return config[key], "config.json"
    return default, "default"


def width_setting():
    return _setting("NX_WIDTH", "width", DEFAULT_WIDTH)


def theme_setting():
    return _setting("NX_THEME", "theme", DEFAULT_THEME)


def theme():
    """colored or plain; an unknown setting is the
    default"""
    setting = str(theme_setting()[0]).strip().lower()
    return setting if setting in THEMES else DEFAULT_THEME


def _width_wanted():
    """the width the setting asks for, or None if it
    is neither a number nor auto"""
    setting, _ = width_setting()
    if str(setting).strip().lower() == "auto":
        # COLUMNS, the terminal, or DEFAULT_WIDTH when
        # the output isn't a terminal
        size = shutil.get_terminal_size((DEFAULT_WIDTH, 24))
        return size.columns
    try:
        return int(setting)
    except (TypeError, ValueError):
        return None


def width():
    """the output width now: the setting, at least
    MIN_WIDTH; read every time, so 'auto' follows the
    terminal when it is resized or the phone turned"""
    wanted = _width_wanted()
    if wanted is None:
        return DEFAULT_WIDTH
    return max(MIN_WIDTH, wanted)


def setting_problems():
    """lines about a width or theme setting that isn't
    used as it is"""
    problems = []
    width_line = _width_problem()
    if width_line:
        problems.append(width_line)
    setting, source = theme_setting()
    if str(setting).strip().lower() not in THEMES:
        problems.append(
            f"theme '{setting}' ({source}) is not "
            f"{' or '.join(THEMES)}, using {DEFAULT_THEME}"
        )
    return problems


def _width_problem():
    """a line about a width setting that isn't used as
    it is, or None"""
    setting, source = width_setting()
    name = source.split()[0]
    if name == "config.json":
        name = "width"
    wanted = _width_wanted()
    if wanted is None:
        return (
            f"{name} '{setting}' is not a number or "
            f"auto, using {DEFAULT_WIDTH}"
        )
    if wanted < MIN_WIDTH:
        auto = str(setting).strip().lower() == "auto"
        what = (
            f"the terminal is {wanted} wide"
            if auto
            else f"{name} {wanted} is too narrow"
        )
        return f"{what}, using {MIN_WIDTH}"
    return None


def _gap(columns, base):
    """the gap between the columns of a table made for
    DEFAULT_WIDTH: base, plus a share of the width beyond
    DEFAULT_WIDTH"""
    if not columns or columns < 2:
        return base
    growth = (width() - DEFAULT_WIDTH) // (columns - 1)
    return base + max(0, min(growth, MAX_GAP_GROWTH))


def color_off_reason():
    """why the output has no colors, or None if it has
    them"""
    if os.environ.get("NO_COLOR"):
        return "NO_COLOR is set"
    if not sys.stdout.isatty():
        return "the output is not a terminal"
    if theme() == "plain":
        return "the theme is plain"
    return None


def supports_color():
    if color_off_reason():
        return False
    if os.name == "nt":
        # enables ANSI escape codes in the Windows console
        os.system("")
    return True


def column_separator(color, columns=None):
    """' | ' between the columns of a table of columns
    columns, wider on a wider screen; without columns it
    stays ' | '"""
    extra = _gap(columns, 3) - 3
    left = 1 + extra // 2
    sep = " " * left + "|" + " " * (1 + extra - extra // 2)
    return f"{DIM}{sep}{RESET}" if color else sep


def space_separator(columns, base):
    """base spaces between the columns of a table of
    columns columns, more on a wider screen"""
    return " " * _gap(columns, base)


def print_dim(text):
    print(
        f"{DIM}{text}{RESET}" if supports_color() else text
    )


def print_wrapped(text):
    """print plain text wrapped to width(), dimmed"""
    print_dim(_wrap(text))


def print_error(text):
    """print an error wrapped to width(), not dimmed so
    it stands out"""
    print(_wrap(text))


def _wrap(text):
    return textwrap.fill(
        text,
        width(),
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


def stock_names():
    return [s.name for s in Stock]


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

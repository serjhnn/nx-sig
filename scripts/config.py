# config: reads config.json once, at the first import,
# and gives every module its settings through typed
# accessors with their defaults
#
#   python tests/test_config.py  the tests
#
# the accessors read DATA on every call, so a test can
# patch that one dict
#
#   ROOT_DIR         the repo root (config.json, .env)
#   DEMO             True in the demo (./nxdemo sets
#                    NX_DEMO=1): DATA is then read from
#                    demo/config.json
#   DEMO_SEED_DIR    the demo's sample data
#   DATA             config.json as read
#   indices()        [symbol] of the tracked stocks
#   demo()           True in the demo
#   demo_prices()    {symbol: starting price}
#   demo_number(key) a positive "demo" setting
#   demo_seed()      the random seed or None
#   storage_dir()    the data folder, absolute
#   url(), feed()    the latest trades endpoint, its feed
#   bars_url()       the bars endpoint (chart)
#   bars_feed()      the bars feed (delayed_sip is sip)
#   notify()         the notify channel name
#   interval(key)    "timing" key in seconds
#   width_setting(), theme_setting()
#                    (setting, "config.json"|"default")
#   theme()          colored or plain
#   chart_height()   the chart's price rows

import json
import os

ROOT_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
DEMO = os.environ.get("NX_DEMO") == "1"
DEMO_DIR = os.path.join(ROOT_DIR, "demo")
DEMO_SEED_DIR = os.path.join(DEMO_DIR, "seed")
# the demo has its own settings and data folder, so
# it never touches the real ones
PATH = os.path.join(
    DEMO_DIR if DEMO else ROOT_DIR, "config.json"
)

with open(PATH) as f:
    DATA = json.load(f)

DEFAULT_STORAGE_DIR = "./data/"
DEFAULT_FEED = "iex"
DEFAULT_BARS_URL = (
    "https://data.alpaca.markets/v2/stocks/bars"
)
NOTIFY_CHANNELS = ("telegram", "termux", "ntfy")
DEFAULT_NOTIFY = "telegram"
DEFAULT_INTERVAL = 30
# the width the shell's tables are made for
DEFAULT_WIDTH = 48
THEMES = ("colored", "plain")
DEFAULT_THEME = "colored"
# the demo's "demo" settings: daily volatility, how
# many times faster than real time the prices move,
# seconds between two moves
DEMO_DEFAULTS = {
    "volatility": 0.05,
    "speed": 300,
    "interval": 2,
}
DEMO_START_PRICE = 50.0
# the chart's price rows, at least MIN_ROWS
DEFAULT_ROWS = 15
MIN_ROWS = 3


def _required(key):
    if key not in DATA:
        raise KeyError(f'config.json has no "{key}"')
    return DATA[key]


def _section(key):
    section = DATA.get(key)
    return section if isinstance(section, dict) else {}


def _is_number(value):
    return isinstance(
        value, (int, float)
    ) and not isinstance(value, bool)


def indices():
    """[symbol] of config "indices", in their order"""
    return list(_required("indices"))


def demo():
    """True in the demo, started with ./nxdemo"""
    return DEMO


def demo_prices():
    """{symbol: starting price} of the demo, for every
    symbol of indices(); DEMO_START_PRICE where
    "demo" "prices" has no positive number"""
    given = _section("demo").get("prices")
    given = given if isinstance(given, dict) else {}
    found = {}
    for symbol in indices():
        price = given.get(symbol)
        ok = _is_number(price) and price > 0
        found[symbol] = price if ok else DEMO_START_PRICE
    return found


def demo_number(key):
    """the "demo" key of DEMO_DEFAULTS: a positive
    number, else its default"""
    value = _section("demo").get(key)
    if _is_number(value) and value > 0:
        return value
    return DEMO_DEFAULTS[key]


def demo_seed():
    """the "demo" "seed", an int, or None for other
    prices each time"""
    seed = _section("demo").get("seed")
    if isinstance(seed, int) and not isinstance(seed, bool):
        return seed
    return None


def storage_dir():
    """the data folder: "storage_dir" relative to the
    repo root (or absolute)"""
    folder = DATA.get("storage_dir") or DEFAULT_STORAGE_DIR
    return os.path.normpath(os.path.join(ROOT_DIR, folder))


def url():
    """the latest trades endpoint"""
    return _required("url")


def feed():
    """the feed of the latest trades"""
    return DATA.get("feed") or DEFAULT_FEED


def bars_url():
    return DATA.get("bars_url") or DEFAULT_BARS_URL


def bars_feed():
    """config "bars_feed", or "feed"; there is no
    delayed_sip feed for bars, so it is sip"""
    name = DATA.get("bars_feed") or feed()
    return "sip" if name == "delayed_sip" else name


def notify():
    """the notify channel name, raises ValueError if
    it is unknown"""
    name = DATA.get("notify", DEFAULT_NOTIFY)
    if name not in NOTIFY_CHANNELS:
        raise ValueError(
            'config.json "notify" must be '
            + " or ".join(f'"{n}"' for n in NOTIFY_CHANNELS)
            + f", not {name!r}"
        )
    return name


def interval(key):
    """config "timing" key in seconds: a positive
    number, else DEFAULT_INTERVAL"""
    value = _section("timing").get(key)
    if _is_number(value) and value > 0:
        return value
    return DEFAULT_INTERVAL


def _terminal(key, default):
    section = _section("terminal")
    if key in section:
        return section[key], "config.json"
    return default, "default"


def width_setting():
    """(setting, where it comes from): a number or
    "auto", as written"""
    return _terminal("width", DEFAULT_WIDTH)


def theme_setting():
    return _terminal("theme", DEFAULT_THEME)


def theme():
    """colored or plain; an unknown setting is the
    default"""
    setting = str(theme_setting()[0]).strip().lower()
    return setting if setting in THEMES else DEFAULT_THEME


def chart_height():
    """config "terminal" "chart_height": an int of at
    least MIN_ROWS, else DEFAULT_ROWS"""
    rows = _section("terminal").get("chart_height")
    if (
        isinstance(rows, int)
        and not isinstance(rows, bool)
        and rows >= MIN_ROWS
    ):
        return rows
    return DEFAULT_ROWS

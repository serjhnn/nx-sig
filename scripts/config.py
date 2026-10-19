# config: reads config.json once, at the first import,
# and gives every module its settings through typed
# accessors with their defaults
#
#   python scripts/config.py   run the tests
#
# the accessors read DATA on every call, so a test can
# patch that one dict
#
#   ROOT_DIR         the repo root (config.json, .env)
#   DATA             config.json as read
#   indices()        [symbol] of the tracked stocks
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
PATH = os.path.join(ROOT_DIR, "config.json")

with open(PATH) as f:
    DATA = json.load(f)

DEFAULT_STORAGE_DIR = "./data/"
DEFAULT_FEED = "iex"
DEFAULT_BARS_URL = (
    "https://data.alpaca.markets/v2/stocks/bars"
)
NOTIFY_CHANNELS = ("telegram", "termux")
DEFAULT_NOTIFY = "telegram"
DEFAULT_INTERVAL = 30
# the width the shell's tables are made for
DEFAULT_WIDTH = 48
THEMES = ("colored", "plain")
DEFAULT_THEME = "colored"
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


if __name__ == "__main__":
    import unittest
    from unittest import mock

    class ConfigTest(unittest.TestCase):
        def patch(self, values):
            p = mock.patch.dict(DATA, values, clear=True)
            p.start()
            self.addCleanup(p.stop)

        def test_file(self):
            with open(PATH) as f:
                self.assertEqual(DATA, json.load(f))
            self.assertTrue(indices())
            self.assertIn(notify(), NOTIFY_CHANNELS)

        def test_required(self):
            self.patch({})
            for accessor in (indices, url):
                with self.assertRaises(KeyError):
                    accessor()

        def test_defaults(self):
            self.patch({"indices": ["SOXL"]})
            self.assertEqual(
                storage_dir(),
                os.path.join(ROOT_DIR, "data"),
            )
            self.assertEqual(feed(), "iex")
            self.assertEqual(bars_feed(), "iex")
            self.assertEqual(bars_url(), DEFAULT_BARS_URL)
            self.assertEqual(notify(), "telegram")
            self.assertEqual(
                width_setting(), (48, "default")
            )
            self.assertEqual(theme(), "colored")
            self.assertEqual(chart_height(), 15)

        def test_feeds(self):
            self.patch({"feed": "delayed_sip"})
            self.assertEqual(bars_feed(), "sip")
            DATA["bars_feed"] = "iex"
            self.assertEqual(bars_feed(), "iex")
            self.assertEqual(feed(), "delayed_sip")

        def test_storage_dir(self):
            self.patch({"storage_dir": "/x/y/"})
            self.assertEqual(storage_dir(), "/x/y")

        def test_notify(self):
            self.patch({"notify": "termux"})
            self.assertEqual(notify(), "termux")
            DATA["notify"] = "mail"
            with self.assertRaises(ValueError) as e:
                notify()
            self.assertIn("'mail'", str(e.exception))

        def test_interval(self):
            key = "ladder_interval"
            bad = ({}, None, [30], {key: 0}, {key: True})
            for timing in bad:
                self.patch({"timing": timing})
                self.assertEqual(interval(key), 30, timing)
            self.patch({"timing": {key: 5}})
            self.assertEqual(interval(key), 5)
            self.assertEqual(interval("alert_interval"), 30)

        def test_terminal(self):
            self.patch({"terminal": {"width": "auto"}})
            self.assertEqual(
                width_setting(), ("auto", "config.json")
            )
            self.assertEqual(
                theme_setting(), ("colored", "default")
            )
            DATA["terminal"] = {"theme": " Plain "}
            self.assertEqual(theme(), "plain")
            DATA["terminal"] = {"theme": "dark"}
            self.assertEqual(theme(), "colored")
            DATA["terminal"] = None
            self.assertEqual(width_setting()[1], "default")

        def test_chart_height(self):
            self.patch({"terminal": {"chart_height": 9}})
            self.assertEqual(chart_height(), 9)
            for bad in (2, "15", 15.0, True, None):
                DATA["terminal"]["chart_height"] = bad
                self.assertEqual(chart_height(), 15, bad)

    unittest.main()

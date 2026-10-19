# tests of scripts/config.py
#
#   python tests/test_config.py

import json
import os

import unittest
from unittest import mock

import paths  # noqa: F401, scripts/ on sys.path
from config import (
    DATA,
    DEFAULT_BARS_URL,
    NOTIFY_CHANNELS,
    PATH,
    ROOT_DIR,
    bars_feed,
    bars_url,
    chart_height,
    feed,
    indices,
    interval,
    notify,
    storage_dir,
    theme,
    theme_setting,
    url,
    width_setting,
)


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
        self.assertEqual(width_setting(), (48, "default"))
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
        DATA["notify"] = "ntfy"
        self.assertEqual(notify(), "ntfy")
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


if __name__ == "__main__":
    unittest.main()

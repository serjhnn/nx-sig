# tests of scripts/engines/demo_prices.py and the demo
# settings in config.py
#
#   python tests/test_demo_prices.py

import json
import math
import os
import random
import tempfile
import unittest
from datetime import datetime
from unittest import mock

import paths  # noqa: F401, scripts/ on sys.path
import config
import storage
from engines import demo_prices
from engines.demo_prices import DAY, HISTORY, MAX_GAP

NOW = 1_800_000_000


def demo_data():
    path = os.path.join(config.DEMO_DIR, "config.json")
    with open(path) as f:
        return json.load(f)


class DemoPricesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db_dir = storage.DB_DIR
        storage.DB_DIR = self._tmp.name
        p = mock.patch.dict(
            config.DATA, demo_data(), clear=True
        )
        p.start()
        self.addCleanup(p.stop)
        self.start = config.demo_prices()
        demo_prices.create(NOW, random.Random(1))

    def tearDown(self):
        storage.DB_DIR = self._orig_db_dir
        self._tmp.cleanup()

    def test_create(self):
        self.assertEqual(demo_prices.latest(), self.start)
        history = storage.demo_bars_get()
        self.assertEqual(
            set(history), set(config.indices())
        )
        for symbol, points in history.items():
            times = [t for t, _ in points]
            self.assertEqual(times, sorted(times))
            self.assertLess(len(points), 2000)
            self.assertGreaterEqual(NOW - times[0], HISTORY)
            self.assertEqual(
                points[-1],
                [NOW, round(self.start[symbol], 2)],
            )
            self.assertTrue(all(p > 0 for _, p in points))

    def test_move_seeded(self):
        # the same seed, the same prices
        first = demo_prices.move(NOW + 2, random.Random(7))
        demo_prices.create(NOW, random.Random(1))
        again = demo_prices.move(NOW + 2, random.Random(7))
        self.assertEqual(first, again)
        self.assertNotEqual(first, self.start)
        self.assertEqual(demo_prices.latest(), first)

    def test_no_time_no_move(self):
        moved = demo_prices.move(NOW, random.Random(3))
        for symbol, price in self.start.items():
            self.assertAlmostEqual(moved[symbol], price)

    def test_pause(self):
        # a pause moves as much as MAX_GAP seconds
        later = NOW + 3600
        paused = demo_prices.move(later, random.Random(5))
        demo_prices.create(NOW, random.Random(1))
        gap = demo_prices.move(
            NOW + MAX_GAP, random.Random(5)
        )
        self.assertEqual(paused, gap)

    def test_stays_near_start(self):
        # 100 moves at 3000 times the speed: about
        # 6000 days of demo time
        config.DATA["demo"]["speed"] = 900_000
        rng = random.Random(11)
        for i in range(1, 101):
            prices = demo_prices.move(NOW + i * 60, rng)
        for symbol, price in prices.items():
            ratio = price / self.start[symbol]
            self.assertLess(abs(math.log(ratio)), 1.5)

    def test_record_once_a_minute(self):
        def newest():
            return storage.demo_bars_get()["SOXL"][-1]

        demo_prices.move(NOW + 30, random.Random(2))
        self.assertEqual(newest()[0], NOW)
        demo_prices.move(NOW + 60, random.Random(2))
        price = demo_prices.latest()["SOXL"]
        self.assertEqual(
            newest(), [NOW + 60, round(price, 2)]
        )
        demo_prices.move(NOW + 62, random.Random(2))
        self.assertEqual(newest()[0], NOW + 60)

    def test_thin(self):
        # a day of minute points: kept for 6 hours,
        # then 15 minutes apart
        end = NOW + DAY
        points = [
            [NOW + i * 60, 1.0] for i in range(24 * 60 + 1)
        ]
        kept = demo_prices._thin(points, end)
        self.assertEqual(kept[-1], points[-1])
        recent = [t for t, _ in kept if end - t < 6 * 3600]
        older = [t for t, _ in kept if end - t >= 6 * 3600]
        self.assertEqual(len(recent), 6 * 60)
        self.assertLessEqual(len(older), 18 * 4 + 2)
        gaps = [b - a for a, b in zip(older, older[1:])]
        self.assertTrue(all(g >= 15 * 60 for g in gaps))
        # older than HISTORY: dropped
        old = [[end - HISTORY - 1, 1.0], [end, 1.0]]
        self.assertEqual(
            demo_prices._thin(old, end), [[end, 1.0]]
        )
        # the made history stays as it is
        history = storage.demo_bars_get()["SOXL"]
        self.assertEqual(
            demo_prices._thin(history, NOW), history
        )

    def test_bars(self):
        found = demo_prices.bars("SOXL", 5, NOW + 1)
        self.assertTrue(
            all(isinstance(t, datetime) for t, _ in found)
        )
        first = datetime.fromtimestamp(NOW + 1 - 5 * DAY)
        self.assertGreaterEqual(found[0][0], first)
        self.assertEqual(found[-1][1], self.start["SOXL"])
        times = [t for t, _ in found]
        self.assertEqual(times, sorted(times))
        self.assertEqual(demo_prices.bars("XX", 5), [])

    def test_ensure(self):
        demo_prices.move(NOW + 2, random.Random(2))
        moved = demo_prices.latest()
        demo_prices.ensure()
        self.assertEqual(demo_prices.latest(), moved)
        os.remove(
            os.path.join(self._tmp.name, "demo_bars.json")
        )
        demo_prices.ensure()
        self.assertEqual(demo_prices.latest(), self.start)


class DemoConfigTest(unittest.TestCase):
    def patch(self, values):
        p = mock.patch.dict(config.DATA, values, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def test_file(self):
        self.patch(demo_data())
        start = config.demo_prices()
        self.assertEqual(list(start), config.indices())
        self.assertNotIn(
            config.DEMO_START_PRICE, start.values()
        )
        self.assertIsNone(config.demo_seed())

    def test_defaults(self):
        self.patch(
            {
                "indices": ["SOXL", "MUU"],
                "demo": {
                    "prices": {"SOXL": 30, "MUU": -1},
                    "speed": 0,
                    "interval": True,
                    "seed": "1",
                },
            }
        )
        self.assertEqual(
            config.demo_prices(),
            {"SOXL": 30, "MUU": config.DEMO_START_PRICE},
        )
        for key, value in config.DEMO_DEFAULTS.items():
            self.assertEqual(config.demo_number(key), value)
        self.assertIsNone(config.demo_seed())
        config.DATA["demo"] = {"seed": 5, "speed": 10}
        self.assertEqual(config.demo_seed(), 5)
        self.assertEqual(config.demo_number("speed"), 10)


if __name__ == "__main__":
    unittest.main()

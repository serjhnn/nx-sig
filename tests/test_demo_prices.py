# tests of scripts/engines/demo_prices.py and the demo
# settings in config.py
#
#   python tests/test_demo_prices.py

import json
import math
import os
import random
import tempfile
import time
import unittest
from datetime import datetime
from unittest import mock

import paths  # noqa: F401, scripts/ on sys.path
import config
import process
import storage
from engines import demo_prices, prices
from engines.demo_prices import DAY, HISTORY, MAX_GAP
from services import demo_prices_service

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

    def test_set_and_shift(self):
        self.assertEqual(
            demo_prices.set_price("SOXL", 20)["SOXL"], 20
        )
        moved = demo_prices.shift(["SOXL", "MUU"], -10)
        self.assertEqual(moved["SOXL"], 18)
        self.assertAlmostEqual(
            moved["MUU"], self.start["MUU"] * 0.9, 3
        )
        self.assertEqual(demo_prices.latest(), moved)
        for bad in (
            lambda: demo_prices.set_price("SOXL", 0),
            lambda: demo_prices.shift(["SOXL"], -91),
            lambda: demo_prices.shift(["SOXL"], 1001),
        ):
            with self.assertRaises(
                demo_prices.DemoPricesError
            ):
                bad()
        # moves on from the price set
        demo_prices.move(NOW, random.Random(1))
        self.assertAlmostEqual(
            demo_prices.latest()["SOXL"], 18
        )

    def test_speed(self):
        self.assertEqual(demo_prices.speed(), 300)
        demo_prices.set_speed(1)
        self.assertEqual(demo_prices.speed(), 1)
        # slower: a smaller move than at 300
        slow = demo_prices.move(NOW + 60, random.Random(9))
        self.assertEqual(demo_prices.speed(), 1)
        demo_prices.create(NOW, random.Random(1))
        self.assertEqual(demo_prices.speed(), 300)
        fast = demo_prices.move(NOW + 60, random.Random(9))

        def moved(prices):
            return abs(prices["SOXL"] - self.start["SOXL"])

        self.assertLess(moved(slow), moved(fast))
        for bad in (0, 10_001):
            with self.assertRaises(
                demo_prices.DemoPricesError
            ):
                demo_prices.set_speed(bad)

    def test_no_prices_yet(self):
        os.remove(
            os.path.join(self._tmp.name, "demo_prices.json")
        )
        for change in (
            lambda: demo_prices.set_price("SOXL", 1),
            lambda: demo_prices.shift(["SOXL"], 5),
            lambda: demo_prices.set_speed(5),
        ):
            with self.assertRaises(
                demo_prices.DemoPricesError
            ):
                change()

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

    def test_bars_timeframe(self):
        # evenly spaced like market bars, so the chart's
        # columns are the same time apart
        for timeframe, step in (
            ("15Min", 900),
            ("1Hour", 3600),
            ("1Day", DAY),
        ):
            found = demo_prices.bars(
                "SOXL", 5, NOW + 1, timeframe
            )
            gaps = {
                (b[0] - a[0]).total_seconds()
                for a, b in zip(found, found[1:])
            }
            self.assertEqual(gaps, {step}, timeframe)
            self.assertEqual(
                found[-1][1], self.start["SOXL"]
            )

    def test_even(self):
        points = [(0, 10.0), (100, 20.0), (300, 0.0)]
        self.assertEqual(
            demo_prices._even(points, 100),
            [
                (0, 10.0),
                (100, 20.0),
                (200, 10.0),
                (300, 0.0),
            ],
        )
        # a step that misses the first point
        self.assertEqual(
            demo_prices._even(points, 250),
            [(50, 15.0), (300, 0.0)],
        )

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


class PricesInDemoTest(unittest.TestCase):
    """engines/prices.py in the demo: the made up
    prices, no keys, no network"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db_dir = storage.DB_DIR
        storage.DB_DIR = self._tmp.name
        for target, name, value in (
            (config, "DEMO", True),
            (prices.requests, "get", self.no_network),
            (os, "environ", {}),
        ):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        # now: get_bars() asks for the last days
        demo_prices.create(time.time(), random.Random(1))

    def tearDown(self):
        storage.DB_DIR = self._orig_db_dir
        self._tmp.cleanup()

    def no_network(self, *args, **kwargs):
        self.fail("a request in the demo")

    def test_latest(self):
        found = prices.get_latest_prices("sip")
        self.assertEqual(list(found), config.indices())
        self.assertEqual(found, demo_prices.latest())

    def test_bars(self):
        found = prices.get_bars("SOXL", 5, "15Min")
        self.assertEqual(
            found[-1][1], demo_prices.latest()["SOXL"]
        )
        self.assertGreater(len(found), 100)

    def test_polling(self):
        got = []
        stop = prices.start_polling(
            60, on_update=got.append, on_error=got.append
        )
        stop.set()
        for _ in range(100):
            if got:
                break
            time.sleep(0.01)
        self.assertEqual(got, [demo_prices.latest()])


class FakeChild:
    def __init__(self, pid, code=None):
        self.pid = pid
        self.code = code

    def poll(self):
        return self.code


class DemoPricesProcessTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db_dir = storage.DB_DIR
        storage.DB_DIR = self._tmp.name
        for target, name, value in (
            (config, "DEMO", True),
            (process, "START_CHECK_SECONDS", 0),
        ):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.alive = set()
        self.patch(
            process,
            "process_runs",
            lambda pid, *a: pid in self.alive,
        )
        self.patch(process, "tasks_run", lambda: False)

    def tearDown(self):
        storage.DB_DIR = self._orig_db_dir
        self._tmp.cleanup()

    def patch(self, target, name, value):
        p = mock.patch.object(target, name, value)
        p.start()
        self.addCleanup(p.stop)

    def test_start(self):
        spawned = []

        def spawn(args, out):
            spawned.append(args)
            return FakeChild(500)

        self.patch(process, "spawn", spawn)
        self.assertEqual(demo_prices.start(42), 500)
        self.assertEqual(
            spawned, [[demo_prices.SCRIPT, "run"]]
        )
        status = demo_prices.status()
        self.assertEqual(status["pid"], 500)
        self.assertEqual(status["shell"], 42)
        # running: the next shell is saved, no new one
        self.alive.add(500)
        self.assertEqual(demo_prices.start(43), 500)
        self.assertEqual(len(spawned), 1)
        self.assertEqual(demo_prices.status()["shell"], 43)

    def test_start_fails(self):
        self.patch(
            process, "spawn", lambda *a: FakeChild(5, 1)
        )
        self.patch(process, "START_CHECK_SECONDS", 1)
        with self.assertRaises(demo_prices.DemoPricesError):
            demo_prices.start(42)
        config.DEMO = False
        with self.assertRaises(demo_prices.DemoPricesError):
            demo_prices.start(42)

    def test_needed(self):
        self.assertFalse(demo_prices.needed())
        demo_prices.save_status(500, None, "moving", 42)
        self.assertFalse(demo_prices.needed())
        self.alive.add(42)
        self.assertTrue(demo_prices.needed())
        # the shell closed, a ladder runs
        self.alive.clear()
        self.patch(process, "tasks_run", lambda: True)
        self.assertTrue(demo_prices.needed())

    def test_stop(self):
        self.assertFalse(demo_prices.stop())
        demo_prices.save_status(500, None, "moving", 42)
        self.alive.add(500)
        sent = []

        def kill(pid, sig):
            sent.append(pid)
            self.alive.discard(pid)
            return True

        self.patch(process, "kill", kill)
        self.patch(process, "reap", lambda pid: None)
        self.assertTrue(demo_prices.stop())
        self.assertEqual(sent, [500])

    def test_service(self):
        # moves until nothing needs the prices
        demo_prices.create(NOW, random.Random(1))
        start = demo_prices.latest()
        needed = iter([True, True, False])
        self.patch(
            demo_prices, "needed", lambda: next(needed)
        )
        self.patch(
            demo_prices_service.time,
            "sleep",
            lambda s: None,
        )
        self.patch(process, "setup_logging", lambda p: None)
        self.patch(process, "release_if_idle", lambda: None)
        demo_prices_service.run()
        self.assertEqual(
            demo_prices.status()["state"], "done"
        )
        self.assertNotEqual(demo_prices.latest(), start)

    def test_service_outside_demo(self):
        config.DEMO = False
        self.patch(process, "setup_logging", lambda p: None)
        self.patch(process, "release_if_idle", lambda: None)
        with self.assertRaises(SystemExit):
            with self.assertLogs("demo_prices", "ERROR"):
                demo_prices_service.run()


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

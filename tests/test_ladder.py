# tests of scripts/engines/ladder.py
#
#   python tests/test_ladder.py

import unittest
from datetime import datetime, timedelta
from unittest import mock

import paths  # noqa: F401, scripts/ on sys.path
from engines import ladder as engine
from engines.ladder import (
    LadderError,
    create,
    levels,
    next_level,
    passed_level,
)


def ladder(direction, step, last):
    return {
        "Id": 1,
        "Stock": "SOXL",
        "Direction": direction,
        "Step": step,
        "From": last,
        "Last": last,
    }


class LevelsTest(unittest.TestCase):
    def test_next_level(self):
        self.assertEqual(
            next_level(ladder("down", 10, 100)), 90
        )
        self.assertEqual(
            next_level(ladder("up", 2.5, 80)), 82.5
        )

    def test_levels(self):
        self.assertEqual(
            levels(ladder("down", 10, 100), 3),
            [90, 80, 70],
        )
        self.assertEqual(
            levels(ladder("up", 0.1, 0.3), 3),
            [0.4, 0.5, 0.6],
        )
        # a down ladder ends above 0
        self.assertEqual(
            levels(ladder("down", 10, 25), 4), [15, 5]
        )
        self.assertEqual(
            levels(ladder("down", 10, 5), 3), []
        )
        # the first is next_level()
        down = ladder("down", 0.5, 22.25)
        self.assertEqual(
            levels(down, 1), [next_level(down)]
        )

    def test_down_not_reached(self):
        down = ladder("down", 10, 100)
        self.assertIsNone(passed_level(down, 95))
        self.assertIsNone(passed_level(down, 90.01))
        self.assertIsNone(passed_level(down, 120))

    def test_down_passed(self):
        down = ladder("down", 10, 100)
        self.assertEqual(passed_level(down, 90), 90)
        self.assertEqual(passed_level(down, 85), 90)
        # several levels at once: the farthest
        self.assertEqual(passed_level(down, 71), 80)
        self.assertEqual(passed_level(down, 70), 70)

    def test_up_passed(self):
        up = ladder("up", 10, 100)
        self.assertIsNone(passed_level(up, 109.99))
        self.assertEqual(passed_level(up, 110), 110)
        self.assertEqual(passed_level(up, 131), 130)
        self.assertIsNone(passed_level(up, 80))

    def test_float_steps(self):
        up = ladder("up", 0.1, 0.3)
        self.assertEqual(passed_level(up, 0.4), 0.4)
        down = ladder("down", 0.1, 0.3)
        self.assertEqual(passed_level(down, 0.1), 0.1)

    def test_create_checks(self):
        for args in (
            ("SOXL", "left", 10, 100),
            ("SOXL", "down", 0, 100),
            ("SOXL", "up", 10, -1),
            ("SOXL", "down", 100, 100),
        ):
            with self.assertRaises(LadderError):
                create(*args)


class TaskTest(unittest.TestCase):
    """ladder.tasks(): the 'ls tasks' rows"""

    def setUp(self):
        self.now = datetime.now().replace(microsecond=0)
        saved = [
            {"Id": 1, "Stock": "SOXL"},
            {"Id": 2, "Stock": "NVDL"},
            {"Id": 3, "Stock": "TSMX"},
        ]
        beats = {
            1: self.beat(0, "waiting"),
            2: self.beat(
                engine.STALE_SECONDS + 1, "waiting"
            ),
        }
        for name, value in (
            ("get_all", lambda: saved),
            # ladder 3 doesn't run
            ("running_pid", {1: 11, 2: 12}.get),
            ("status", beats.get),
        ):
            p = mock.patch.object(engine, name, value)
            p.start()
            self.addCleanup(p.stop)

    def beat(self, ago, state):
        updated = self.now - timedelta(seconds=ago)
        return {
            "started": self.now.isoformat(),
            "updated": updated.isoformat(),
            "state": state,
        }

    def test_rows(self):
        self.assertEqual(
            engine.tasks(),
            [
                {
                    "id": 1,
                    "task": "ladder SOXL",
                    "pid": 11,
                    "started": self.now,
                    "state": "waiting",
                    "healthy": True,
                },
                {
                    "id": 2,
                    "task": "ladder NVDL",
                    "pid": 12,
                    "started": self.now,
                    "state": "no reply",
                    "healthy": False,
                },
            ],
        )


class RowsTest(unittest.TestCase):
    """ladder.rows(): the 'ls ladders' rows"""

    def setUp(self):
        def saved(i, direction, step, last):
            return {
                "Id": i,
                "Stock": "SOXL",
                "Direction": direction,
                "Step": step,
                "From": 35.0,
                "Last": last,
                "Created": "20.10.2026 15:30",
            }

        self.saved = [
            saved(1, "down", 1.0, 35.0),
            saved(2, "up", 2.5, 35.0),
            saved(3, "down", 10.0, 5.0),
            saved(4, "down", 0.5, 30.0),
            saved(5, "down", 1.0, 33.0),
        ]
        beats = {
            # its process ended without a stop
            2: {"state": "waiting"},
            3: {"state": "done"},
            4: {"state": "crashed"},
        }
        for name, value in (
            ("get_all", lambda: self.saved),
            ("running_pid", {1: 11}.get),
            ("status", beats.get),
        ):
            p = mock.patch.object(engine, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_rows(self):
        rows = engine.rows()
        self.assertEqual(
            [(r["Id"], r["state"], r["pid"]) for r in rows],
            [
                (1, "running", 11),
                (2, "stopped", None),
                (3, "done", None),
                (4, "crashed", None),
                (5, "stopped", None),
            ],
        )
        self.assertEqual(
            [r["next"] for r in rows],
            [34.0, 37.5, None, 29.5, 32.0],
        )
        # the saved fields stay
        for row, saved in zip(rows, self.saved):
            self.assertEqual(
                {k: row[k] for k in saved}, saved
            )

    def test_one_row(self):
        self.assertEqual(
            engine.row(self.saved[0]), engine.rows()[0]
        )


if __name__ == "__main__":
    unittest.main()

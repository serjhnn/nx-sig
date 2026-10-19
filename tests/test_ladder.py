# tests of scripts/engines/ladder.py
#
#   python tests/test_ladder.py

import unittest

import paths  # noqa: F401, scripts/ on sys.path
from engines.ladder import (
    LadderError,
    create,
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


if __name__ == "__main__":
    unittest.main()

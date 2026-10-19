# tests of scripts/alerts.py
#
#   python tests/test_alerts.py

import logging

import unittest
from unittest import mock

import paths  # noqa: F401, scripts/ on sys.path
from storage import Stock, alerts_get_all
import storage
from alerts import (
    AlertError,
    _check,
    _now,
    _status,
    basetrade_levels,
    check,
    create,
    create_gain,
    describe,
    gain_level,
    level,
    past,
    positions_get,
    rearmed,
    start,
)

import tempfile

DOWN = {"Id": 1, "Direction": "down", "Percent": 10}
UP = {"Id": 2, "Direction": "up", "Percent": 20}


def bought(price):
    return [{"Stock": "MRVU", "Price": price}]


class LevelsTest(unittest.TestCase):
    def test_level(self):
        self.assertEqual(level(100, DOWN), 90)
        self.assertEqual(level(100, UP), 120)
        self.assertEqual(level(20.5, DOWN), 18.45)

    def test_past(self):
        self.assertFalse(past(DOWN, 90, 90.01))
        self.assertTrue(past(DOWN, 90, 90))
        self.assertTrue(past(DOWN, 90, 50))
        self.assertFalse(past(UP, 120, 119.99))
        self.assertTrue(past(UP, 120, 120))

    def test_rearmed(self):
        # 1% of the buying price 100 past 90
        self.assertFalse(rearmed(DOWN, 90, 100, 90.99))
        self.assertTrue(rearmed(DOWN, 90, 100, 91))
        self.assertFalse(rearmed(UP, 120, 100, 119.5))
        self.assertTrue(rearmed(UP, 120, 100, 119))


class CheckTest(unittest.TestCase):
    def step(self, price, base=100, alerts=(DOWN,)):
        """one check at price, return the stocks
        the messages are about"""
        self.past, messages = check(
            list(alerts),
            bought(base),
            [],
            {"MRVU": price} if price else {},
            self.past,
        )
        # as if every message was sent
        for alert_id, name, base, _ in messages:
            self.past[str(alert_id)][name] = base
        return [m[1] for m in messages]

    def setUp(self):
        self.past = {}

    def test_every_crossing(self):
        self.assertEqual(self.step(95), [])
        self.assertEqual(self.step(89.5), ["MRVU"])
        # still past: no new message
        self.assertEqual(self.step(85), [])
        # back over 90 but within 1%: no new one
        self.assertEqual(self.step(90.5), [])
        self.assertEqual(self.step(89), [])
        # back over 91 and down again: sent again
        self.assertEqual(self.step(92), [])
        self.assertEqual(self.past, {"1": {}})
        self.assertEqual(self.step(90), ["MRVU"])

    def test_text(self):
        _, messages = check(
            [DOWN, UP],
            bought(100),
            [],
            {"MRVU": 89.5},
            {},
        )
        self.assertEqual(
            [m[3] for m in messages],
            [
                "MRVU -10.5% at 89.50, bought at 100 "
                "(alert 1: down 10%)"
            ],
        )

    def test_already_past_is_sent(self):
        self.assertEqual(self.step(50), ["MRVU"])

    def test_new_basetrade_starts_over(self):
        self.step(89)
        # bought again at 95: past its 85.5? no
        self.assertEqual(self.step(89, base=95), [])
        self.assertEqual(self.past, {"1": {}})
        self.assertEqual(self.step(85, base=95), ["MRVU"])

    def test_no_price_keeps_the_state(self):
        self.step(89)
        self.assertEqual(self.step(None), [])
        self.assertEqual(self.past, {"1": {"MRVU": 100}})

    def test_removed_alert_is_dropped(self):
        self.past = {"7": {"MRVU": 100}}
        self.step(95)
        self.assertEqual(self.past, {"1": {}})


def gain(stock, value, percent=False, alert_id=3):
    return {
        "Id": alert_id,
        "For": "gain",
        "Stock": stock,
        "Direction": "down" if value < 0 else "up",
        "Percent": abs(value) if percent else None,
        "Amount": None if percent else abs(value),
    }


class GainTest(unittest.TestCase):
    # 10 TSMX at 60 on average, 5 SOXL at 20
    POSITIONS = [("TSMX", 10, 60.0), ("SOXL", 5, 20.0)]

    def step(self, alert, prices, positions=None):
        self.past, messages = check(
            [alert],
            [],
            positions or self.POSITIONS,
            prices,
            self.past,
        )
        for alert_id, name, key, _ in messages:
            self.past[str(alert_id)][name] = key
        return [m[3] for m in messages]

    def setUp(self):
        self.past = {}

    def test_levels(self):
        self.assertEqual(
            gain_level(gain("TSMX", 100), 10, 60), 70
        )
        self.assertEqual(
            gain_level(gain("all", -50), 5, 20), 10
        )
        self.assertEqual(
            gain_level(gain("all", 10, True), 10, 60),
            66,
        )

    def test_describe(self):
        self.assertEqual(
            describe(gain("TSMX", 100)), "TSMX +100"
        )
        self.assertEqual(
            describe(gain("all", -10, True)), "all -10%"
        )

    def test_amount(self):
        alert = gain("TSMX", 100)
        self.assertEqual(
            self.step(alert, {"TSMX": 69.9}), []
        )
        self.assertEqual(
            self.step(alert, {"TSMX": 70.5}),
            [
                "TSMX gain +105.00 (+17.5%) at 70.50 "
                "(alert 3: gain TSMX +100)"
            ],
        )
        # only TSMX, still past
        self.assertEqual(
            self.step(alert, {"TSMX": 71, "SOXL": 99}),
            [],
        )
        # back 1% of the avg (0.60) under 70 and up
        self.assertEqual(
            self.step(alert, {"TSMX": 69.5}), []
        )
        self.assertEqual(self.step(alert, {"TSMX": 70}), [])
        self.step(alert, {"TSMX": 69.3})
        self.assertEqual(
            len(self.step(alert, {"TSMX": 70})), 1
        )

    def test_all_percent_loss(self):
        alert = gain("all", -10, True)
        self.assertEqual(
            self.step(alert, {"TSMX": 53.9, "SOXL": 18.5}),
            [
                "TSMX gain -61.00 (-10.2%) at 53.90 "
                "(alert 3: gain all -10%)"
            ],
        )

    def test_new_trade_starts_over(self):
        alert = gain("TSMX", 100)
        self.step(alert, {"TSMX": 71})
        # 10 more bought at 80: avg 70, the level
        # moves to 70 + 100 / 20 = 75
        moved = [("TSMX", 20, 70.0)]
        self.assertEqual(
            self.step(alert, {"TSMX": 74}, moved), []
        )
        self.assertEqual(
            len(self.step(alert, {"TSMX": 76}, moved)),
            1,
        )

    def test_create_gain_checks(self):
        for args in (
            ("XXX", 100),
            ("TSMX", 0),
            ("all", -100, True),
        ):
            with self.assertRaises(AlertError):
                create_gain(*args)


class ProcessTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._db_dir = storage.DB_DIR
        storage.DB_DIR = self._tmp.name
        self.sent = []
        self.prices = {"MRVU": 89.0}
        for p in (
            mock.patch("alerts.notify", self.sent.append),
            mock.patch(
                "alerts.get_latest_prices",
                lambda: dict(self.prices),
            ),
        ):
            p.start()

    def tearDown(self):
        mock.patch.stopall()
        storage.DB_DIR = self._db_dir
        self._tmp.cleanup()

    def test_check_saves_what_was_sent(self):
        storage.basetrade_set("MRVU", 100.0, 1)
        create("basetrades", "down", 10)
        state, past_now = _check(alerts_get_all())
        self.assertEqual(state, "waiting")
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(past_now, {"1": {"MRVU": 100}})
        _status(1, _now(), state, past_now)
        # the next check knows it was sent
        _check(alerts_get_all())
        self.assertEqual(len(self.sent), 1)

    def test_check_gain_from_trades(self):
        storage.trade_add(
            Stock.MRVU, storage.TradeType.BUY, 2, 80
        )
        create_gain("MRVU", 10)
        self.assertEqual(
            positions_get(), [("MRVU", 2, 80.0)]
        )
        # 89 - 80 = 9 a stock, 18 for 2: past +10
        state, past_now = _check(alerts_get_all())
        self.assertEqual(
            self.sent,
            [
                "MRVU gain +18.00 (+11.2%) at 89.00 "
                "(alert 1: gain MRVU +10)"
            ],
        )
        self.assertEqual(past_now, {"1": {"MRVU": 85}})

    def test_failed_notify_is_sent_again(self):
        def fail(text):
            raise RuntimeError("offline")

        storage.basetrade_set("MRVU", 100.0, 1)
        create("basetrades", "down", 10)
        with mock.patch("alerts.notify", fail):
            state, past_now = _check(alerts_get_all())
        self.assertEqual(state, "no notify")
        self.assertEqual(past_now, {"1": {}})

    def test_create_checks(self):
        for args in (
            ("stocks", "down", 10),
            ("basetrades", "left", 10),
            ("basetrades", "up", 0),
            ("basetrades", "down", 100),
        ):
            with self.assertRaises(AlertError):
                create(*args)
        self.assertEqual(create("basetrades", "up", 150), 1)

    def test_start_without_alerts(self):
        with self.assertRaises(AlertError):
            start()

    def test_basetrade_levels(self):
        create("basetrades", "down", 10)
        rows = basetrade_levels(
            [
                {"Stock": "MRVU", "Price": 100.0},
                {"Stock": "SOXL", "Price": 20.0},
            ],
            {"MRVU": 89.0},
        )
        self.assertEqual(
            [(a["Id"], s) for a, s in rows],
            [
                (
                    1,
                    [
                        ("MRVU", 90.0, True),
                        ("SOXL", 18.0, False),
                    ],
                )
            ],
        )


# the warnings of the failed notify
logging.disable(logging.WARNING)
if __name__ == "__main__":
    unittest.main()

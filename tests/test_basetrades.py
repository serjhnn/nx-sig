# tests of scripts/engines/basetrades.py
#
#   python tests/test_basetrades.py

import tempfile
import unittest

import paths  # noqa: F401, scripts/ on sys.path
import storage
from engines import basetrades, trades
from engines.basetrades import Stock, TradeType

BUY, SELL = TradeType.BUY, TradeType.SELL


class BaseTradesTest(unittest.TestCase):
    def setUp(self):
        # base_trades.csv in a temp dir, real data is not
        # touched
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db_dir = storage.DB_DIR
        storage.DB_DIR = self._tmp.name

    def tearDown(self):
        storage.DB_DIR = self._orig_db_dir
        self._tmp.cleanup()

    def test_save_checks_price_and_count(self):
        for price, count in ((0, 1), (1, 0), (-2, 3)):
            with self.assertRaises(
                basetrades.BaseTradeError
            ):
                basetrades.save(Stock.SOXL, price, count)
        self.assertEqual(basetrades.get_all(), [])

    def test_save_get_delete(self):
        self.assertFalse(
            basetrades.save(Stock.SOXL, 20, 10)
        )
        self.assertTrue(basetrades.save(Stock.SOXL, 18, 5))

        found = basetrades.get("SOXL")
        self.assertEqual(
            (found["Price"], found["Count"]), (18.0, 5)
        )
        self.assertIsNone(basetrades.get("MUU"))

        self.assertEqual(
            basetrades.delete("SOXL")["Count"], 5
        )
        self.assertIsNone(basetrades.delete("SOXL"))
        self.assertEqual(basetrades.get_all(), [])

    def _trades(self, *found):
        # (type, count, price) a day apart, oldest first
        for day, (kind, count, price) in enumerate(
            found, 1
        ):
            trades.add(
                Stock.SOXL,
                kind,
                count,
                price,
                f"{day:02}.10.2026",
                "10:00",
            )

    def _lowest(self):
        found = basetrades.from_trades(Stock.SOXL)
        return found["Price"], found["Count"]

    def test_from_trades_needs_a_buy(self):
        with self.assertRaises(basetrades.BaseTradeError):
            basetrades.from_trades(Stock.SOXL)
        self._trades((BUY, 5, 20), (SELL, 2, 25))
        with self.assertRaises(basetrades.BaseTradeError):
            basetrades.from_trades(Stock.SOXL)

    def test_from_trades_lowest_buy(self):
        # the lowest buy is not the last one
        self._trades(
            (BUY, 5, 20), (BUY, 3, 15), (BUY, 2, 19)
        )
        self.assertEqual(self._lowest(), (15.0, 3))

    def test_from_trades_after_the_last_sell(self):
        # a partial sell starts over, the buy at 10
        # before it doesn't count
        self._trades(
            (BUY, 9, 10),
            (SELL, 2, 12),
            (BUY, 4, 18),
            (BUY, 6, 16),
            (BUY, 1, 17),
        )
        self.assertEqual(self._lowest(), (16.0, 6))

    def test_from_trades_equal_prices(self):
        # the later of two equal buys
        self._trades((BUY, 5, 20), (BUY, 7, 20))
        found = basetrades.from_trades(Stock.SOXL)
        self.assertEqual(
            (found["Count"], found["Date"]),
            (7, "02.10.2026"),
        )
        # nothing saved
        self.assertEqual(basetrades.get_all(), [])

    def test_lowest_buys(self):
        self.assertEqual(basetrades.lowest_buys(), [])
        self._trades((BUY, 5, 20), (BUY, 3, 15))
        trades.add(Stock.TSMX, BUY, 2, 40)
        trades.add(Stock.TSMX, SELL, 2, 45)
        found = basetrades.lowest_buys()
        # each stock that has trades, in config order,
        # None without a buy since the last sell
        self.assertEqual(
            [(s, b and b["Price"]) for s, b in found],
            [(Stock.TSMX, None), (Stock.SOXL, 15.0)],
        )

    def test_all_from_trades(self):
        with self.assertRaises(
            basetrades.BaseTradeError
        ) as e:
            basetrades.all_from_trades()
        self.assertEqual(
            str(e.exception), basetrades.NO_LOWEST
        )
        self._trades((BUY, 5, 20), (BUY, 3, 15))
        trades.add(Stock.TSMX, BUY, 2, 40)
        trades.add(Stock.TSMX, SELL, 2, 45)
        basetrades.save(Stock.SOXL, 30, 1)
        saved = basetrades.all_from_trades()
        self.assertEqual(
            [
                (s, b and b["Price"], replaced)
                for s, b, replaced in saved
            ],
            [
                (Stock.TSMX, None, None),
                (Stock.SOXL, 15.0, True),
            ],
        )
        self.assertEqual(
            basetrades.get_all(),
            [{"Stock": "SOXL", "Price": 15.0, "Count": 3}],
        )

    def test_all_from_trades_of_found(self):
        # only the stocks given, e.g. the ones the
        # shell asked about
        self._trades((BUY, 5, 20))
        trades.add(Stock.TSMX, BUY, 2, 40)
        found = [
            f
            for f in basetrades.lowest_buys()
            if f[0] == Stock.TSMX
        ]
        basetrades.all_from_trades(found)
        self.assertEqual(
            [b["Stock"] for b in basetrades.get_all()],
            ["TSMX"],
        )


if __name__ == "__main__":
    unittest.main()

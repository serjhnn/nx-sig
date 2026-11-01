# tests of scripts/engines/positions.py
#
#   python tests/test_positions.py

import tempfile
import unittest
from unittest import mock

import paths  # noqa: F401, scripts/ on sys.path
import config
import storage
from engines import positions, trades
from storage import Stock, TradeType


class PositionsTest(unittest.TestCase):
    def setUp(self):
        # the trades files in a temp dir, real data is
        # not touched; no config "fee"
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        orig = storage.DB_DIR
        storage.DB_DIR = self._tmp.name
        self.addCleanup(setattr, storage, "DB_DIR", orig)
        p = mock.patch.dict(config.DATA)
        p.start()
        self.addCleanup(p.stop)
        config.DATA.pop("fee", None)

    def buy(self, stock, count, price):
        trades.add(stock, TradeType.BUY, count, price)

    def sell(self, stock, count, price):
        trades.add(stock, TradeType.SELL, count, price)

    def test_held(self):
        self.assertEqual(positions.held(), [])
        self.buy(Stock.SOXL, 10, 20)
        self.buy(Stock.SOXL, 10, 30)
        self.buy(Stock.TSMX, 5, 40)
        # sold out: not held
        self.sell(Stock.TSMX, 5, 50)
        self.assertEqual(
            positions.held(), [(Stock.SOXL, 20, 25.0)]
        )

    def test_rows(self):
        self.buy(Stock.SOXL, 20, 25)
        self.buy(Stock.TSMX, 10, 40)
        rows = positions.rows({"SOXL": 30.0})
        self.assertEqual(
            [r["stock"] for r in rows],
            [
                s
                for s in Stock
                if s.name in ("SOXL", "TSMX")
            ],
        )
        soxl = next(
            r for r in rows if r["stock"].name == "SOXL"
        )
        self.assertEqual(soxl["count"], 20)
        self.assertEqual(soxl["avg"], 25)
        self.assertEqual(soxl["cost"], 500)
        self.assertEqual(soxl["price"], 30.0)
        self.assertEqual(soxl["gain"], 100)
        self.assertEqual(soxl["pct"], 20)
        # no price: no gain
        tsmx = next(
            r for r in rows if r["stock"].name == "TSMX"
        )
        self.assertEqual(tsmx["cost"], 400)
        self.assertIsNone(tsmx["price"])
        self.assertIsNone(tsmx["gain"])
        self.assertIsNone(tsmx["pct"])

    def test_rows_read_the_trades_each_time(self):
        self.buy(Stock.SOXL, 10, 20)
        self.assertEqual(len(positions.rows({})), 1)
        self.buy(Stock.TSMX, 10, 20)
        self.assertEqual(len(positions.rows({})), 2)

    def test_loss(self):
        self.buy(Stock.SOXL, 10, 20)
        (row,) = positions.rows({"SOXL": 15.0})
        self.assertEqual(row["gain"], -50)
        self.assertEqual(row["pct"], -25)

    def test_total(self):
        self.buy(Stock.SOXL, 20, 25)
        self.buy(Stock.TSMX, 10, 40)
        self.buy(Stock.NVDL, 10, 10)
        rows = positions.rows({"SOXL": 30.0, "TSMX": 30.0})
        # NVDL has no price: not in the total
        self.assertEqual(
            positions.total(rows), (0.0, 900.0, 0.0)
        )
        rows = positions.rows({"SOXL": 30.0})
        self.assertEqual(
            positions.total(rows), (100.0, 500.0, 20.0)
        )

    def test_total_without_prices(self):
        self.buy(Stock.SOXL, 20, 25)
        self.assertEqual(
            positions.total(positions.rows({})),
            (0, 0, None),
        )
        self.assertEqual(positions.total([]), (0, 0, None))


if __name__ == "__main__":
    unittest.main()

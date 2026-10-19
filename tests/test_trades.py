# tests of scripts/engines/trades.py
#
#   python tests/test_trades.py

import tempfile
import unittest

import paths  # noqa: F401, scripts/ on sys.path
import storage
from engines import trades
from engines.trades import Stock, TradeType
from storage import _trades_path


class TradesTest(unittest.TestCase):
    def setUp(self):
        # the trades files in a temp dir, real data is
        # not touched
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db_dir = storage.DB_DIR
        storage.DB_DIR = self._tmp.name

    def tearDown(self):
        storage.DB_DIR = self._orig_db_dir
        self._tmp.cleanup()

    def test_add_checks_count_and_price(self):
        for count, price in ((0, 100), (1, 0), (-1, 5)):
            with self.assertRaises(trades.TradeError):
                trades.add(
                    Stock.TSMX, TradeType.BUY, count, price
                )
        self.assertEqual(trades.get_all(Stock.TSMX), [])

    def test_get(self):
        trades.add(Stock.TSMX, TradeType.BUY, 10, 250)
        trades.add(Stock.TSMX, TradeType.SELL, 4, 300)

        self.assertEqual(
            trades.get(Stock.TSMX, 2)["Type"],
            TradeType.SELL,
        )
        self.assertIsNone(trades.get(Stock.TSMX, 3))

    def test_summary_has_stocks_with_trades(self):
        self.assertEqual(trades.summary(), [])
        trades.add(Stock.SOXL, TradeType.BUY, 1, 100)

        found = trades.summary()
        self.assertEqual(
            [stock for stock, _ in found], [Stock.SOXL]
        )
        self.assertEqual(len(found[0][1]), 1)

    def test_total_buy_averages_price(self):
        trades.add(Stock.TSMX, TradeType.BUY, 10, 250)
        trades.add(Stock.TSMX, TradeType.BUY, 10, 270)

        self.assertEqual(
            trades.total(Stock.TSMX),
            (20, 260.0),
        )

    def test_total_sell_keeps_price(self):
        trades.add(Stock.TSMX, TradeType.BUY, 10, 250)
        trades.add(Stock.TSMX, TradeType.SELL, 4, 300)

        self.assertEqual(
            trades.total(Stock.TSMX),
            (6, 250.0),
        )

    def test_total_of_each_stock(self):
        trades.add(Stock.SOXL, TradeType.BUY, 1, 100)
        trades.add(Stock.TSMX, TradeType.BUY, 2, 200)

        self.assertEqual(
            trades.total(Stock.SOXL),
            (1, 100.0),
        )
        self.assertEqual(
            trades.total(Stock.TSMX),
            (2, 200.0),
        )
        self.assertEqual(trades.total(Stock.NVDL), (0, 0.0))

    def test_total_follows_edited_trades_file(self):
        # e.g. a hand edit or a Syncthing conflict
        trades.add(Stock.TSMX, TradeType.BUY, 10, 250)
        path = _trades_path(Stock.TSMX)
        with open(path) as f:
            text = f.read()
        with open(path, "w") as f:
            f.write(text.replace(",10,250", ",4,300"))

        self.assertEqual(
            trades.total(Stock.TSMX),
            (4, 300.0),
        )

    def test_delete_recalculates_total(self):
        trades.add(Stock.TSMX, TradeType.BUY, 10, 250)
        trades.add(Stock.TSMX, TradeType.BUY, 10, 270)
        trades.add(Stock.TSMX, TradeType.SELL, 5, 300)
        trades.add(Stock.SOXL, TradeType.BUY, 1, 100)

        trades.delete(Stock.TSMX, 2)

        self.assertEqual(
            trades.total(Stock.TSMX),
            (5, 250.0),
        )
        self.assertEqual(
            trades.total(Stock.SOXL),
            (1, 100.0),
        )

    def test_delete_last_trade_resets_total(self):
        trades.add(Stock.TSMX, TradeType.BUY, 10, 250)

        self.assertTrue(trades.delete(Stock.TSMX, 1))

        self.assertEqual(trades.get_all(Stock.TSMX), [])
        self.assertEqual(trades.total(Stock.TSMX), (0, 0.0))


if __name__ == "__main__":
    unittest.main()

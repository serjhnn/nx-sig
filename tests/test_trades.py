# tests of scripts/engines/trades.py
#
#   python tests/test_trades.py

import os
import tempfile
import unittest
from unittest import mock

import paths  # noqa: F401, scripts/ on sys.path
import config
import storage
from engines import trades
from engines.trades import Stock, TradeType
from storage import _trades_path


def no_fee(test):
    """no config "fee" during the test, whatever
    config.json says (test_total_with_fee sets one)"""
    p = mock.patch.dict(config.DATA)
    p.start()
    test.addCleanup(p.stop)
    config.DATA.pop("fee", None)


class TradesTest(unittest.TestCase):
    def setUp(self):
        # the trades files in a temp dir, real data is
        # not touched
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db_dir = storage.DB_DIR
        storage.DB_DIR = self._tmp.name
        no_fee(self)

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

    def test_total_with_fee(self):
        config.DATA["fee"] = 5
        trades.add(Stock.TSMX, TradeType.BUY, 10, 18)
        self.assertEqual(
            trades.total(Stock.TSMX), (10, 18.5)
        )
        trades.add(Stock.TSMX, TradeType.BUY, 10, 20)
        # (180 + 5 + 200 + 5) / 20
        self.assertEqual(
            trades.total(Stock.TSMX), (20, 19.5)
        )
        # a sell's fee doesn't change the average
        trades.add(Stock.TSMX, TradeType.SELL, 5, 22)
        self.assertEqual(
            trades.total(Stock.TSMX), (15, 19.5)
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

    def test_add_at_date_and_time(self):
        trades.add(
            Stock.TSMX,
            TradeType.BUY,
            1,
            100,
            "22.10.2026",
            "19:46",
        )
        trade = trades.get(Stock.TSMX, 1)
        self.assertEqual(
            (trade["Date"], trade["Time"]),
            ("22.10.2026", "19:46"),
        )

    def test_add_checks_date_and_time(self):
        for date, time in (
            ("22.10.2026", None),
            (None, "19:46"),
            ("31.02.2026", "19:46"),
            ("2026-10-22", "19:46"),
            ("22.10.2026", "25:00"),
        ):
            with self.assertRaises(trades.TradeError):
                trades.add(
                    Stock.TSMX,
                    TradeType.BUY,
                    1,
                    100,
                    date,
                    time,
                )
        self.assertEqual(trades.get_all(Stock.TSMX), [])


# a statement with a sell of a stock not in the
# indices, a buy, its fee and a row with a bad count;
# newest first, as the bank lists them
STATEMENT = (
    '"23/10/26, 10:00","23/10/26, 10:00","x","y",'
    '"Պատվեր թիվ 3, 2026/10/23, 4.00 հատ AVGG'
    ' վաճառք","+80.00 USD","+80.00 USD"\n'
    '"22/10/26, 19:47","22/10/26, 19:47","x","y",'
    '"Պատվեր թիվ 2, 2026/10/22, 1.50 հատ AVGG'
    ' առք","-30.00 USD","-30.00 USD"\n'
    '"22/10/26, 19:46","22/10/26, 19:46","x","y",'
    '"Միջնորդավճար / Պատվեր թիվ 699534, 2026/10/22,'
    ' 10.00 հատ AVGG առք","-5.00 USD","-5.00 USD"\n'
    '"22/10/26, 19:46","22/10/26, 19:46","x","y",'
    '"Պատվեր թիվ 699534, 2026/10/22, 10.00 հատ AVGG'
    ' առք","-182.19 USD","-182.19 USD"\n'
    '"10/12/25, 23:34","10/12/25, 23:34","x","y",'
    '"Պատվեր թիվ 460827, 2025/12/10, 14.00 հատ VOO'
    ' վաճառք","+8,834.00 USD","+8,834.00 USD"\n'
)


class ImportStatementTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db_dir = storage.DB_DIR
        storage.DB_DIR = self._tmp.name
        self.path = os.path.join(
            self._tmp.name, "statement.csv"
        )
        no_fee(self)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(STATEMENT)

    def tearDown(self):
        storage.DB_DIR = self._orig_db_dir
        self._tmp.cleanup()

    def test_import(self):
        added, skipped = trades.import_statement(self.path)

        self.assertEqual(
            [t["Order"] for t in added], [699534, 3]
        )
        self.assertEqual(
            skipped,
            [
                "row 2: count 1.50",
                "order 460827: no stock VOO",
            ],
        )
        recorded = trades.get_all(Stock.AVGG)
        self.assertEqual(
            [
                (t["Date"], t["Time"], t["Type"])
                for t in recorded
            ],
            [
                ("22.10.2026", "19:46", TradeType.BUY),
                ("23.10.2026", "10:00", TradeType.SELL),
            ],
        )
        self.assertEqual(recorded[0]["Price"], 18.219)
        self.assertEqual(
            trades.total(Stock.AVGG), (6, 18.219)
        )

    def test_import_again_adds_nothing(self):
        trades.import_statement(self.path)
        added, skipped = trades.import_statement(self.path)

        self.assertEqual(added, [])
        self.assertIn(
            "order 699534: already recorded", skipped
        )
        self.assertIn("order 3: already recorded", skipped)
        self.assertEqual(len(trades.get_all(Stock.AVGG)), 2)

    def test_same_trade_twice_in_statement(self):
        # one of the two is recorded already
        trades.add(
            Stock.AVGG,
            TradeType.BUY,
            10,
            18.219,
            "22.10.2026",
            "19:46",
        )
        row = (
            '"22/10/26, 19:46","22/10/26, 19:46","x","y",'
            '"Պատվեր թիվ {}, 2026/10/22, 10.00 հատ AVGG'
            ' առք","-182.19 USD","-182.19 USD"\n'
        )
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(row.format(1) + row.format(2))

        added, skipped = trades.import_statement(self.path)

        self.assertEqual([t["Order"] for t in added], [2])
        self.assertEqual(
            skipped, ["order 1: already recorded"]
        )

    def test_missing_file(self):
        with self.assertRaises(OSError):
            trades.import_statement(
                os.path.join(self._tmp.name, "none.csv")
            )


if __name__ == "__main__":
    unittest.main()

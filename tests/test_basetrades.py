# tests of scripts/engines/basetrades.py
#
#   python tests/test_basetrades.py

import tempfile
import unittest

import paths  # noqa: F401, scripts/ on sys.path
import storage
from engines import basetrades
from engines.basetrades import Stock


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


if __name__ == "__main__":
    unittest.main()

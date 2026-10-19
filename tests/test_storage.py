# tests of scripts/storage.py
#
#   python tests/test_storage.py

import csv
import os
from datetime import datetime

import unittest

import paths  # noqa: F401, scripts/ on sys.path
import storage
from storage import (
    ALERT_FIELDNAMES,
    Stock,
    TRADE_FIELDNAMES,
    TradeType,
    _db_lock,
    _trades_path,
    _write_csv_atomic,
    alert_add,
    alert_delete,
    alerts_get_all,
    alerts_status_get,
    alerts_status_set,
    basetrade_delete,
    basetrade_set,
    basetrades_get_all,
    fcntl,
    ladder_add,
    ladder_delete,
    ladder_get,
    ladder_set_last,
    ladder_status_get,
    ladder_status_set,
    ladders_get_all,
    mail_position_get,
    mail_position_set,
    rules_add,
    rules_delete,
    rules_get_all,
    trade_add,
    trade_delete,
    trades_get_all,
    trades_total_get,
    watcher_status_get,
    watcher_status_set,
)

import tempfile


class TradesTest(unittest.TestCase):
    def setUp(self):
        # redirect csv files to a temp dir so real data
        # is not touched
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db_dir = storage.DB_DIR
        storage.DB_DIR = self._tmp.name

    def tearDown(self):
        storage.DB_DIR = self._orig_db_dir
        self._tmp.cleanup()

    def test_get_without_file_returns_empty(self):
        self.assertEqual(trades_get_all(Stock.SOXL), [])

    def test_add_creates_file_with_header(self):
        trade_add(Stock.TSMX, TradeType.BUY, 10, 250)

        with open(
            _trades_path(Stock.TSMX), newline=""
        ) as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0], TRADE_FIELDNAMES)
        self.assertEqual(rows[1][0], "1")
        self.assertEqual(rows[1][3:], ["BUY", "10", "250"])
        self.assertEqual(len(rows), 2)

    def test_add_and_get_roundtrip(self):
        trade_add(Stock.TSMX, TradeType.BUY, 10, 250)
        trade_add(Stock.TSMX, TradeType.SELL, 5, 260.5)

        trades = trades_get_all(Stock.TSMX)
        self.assertEqual(len(trades), 2)
        self.assertEqual([t["Id"] for t in trades], [1, 2])
        self.assertEqual(trades[0]["Type"], TradeType.BUY)
        self.assertEqual(trades[0]["Count"], 10)
        self.assertEqual(trades[0]["Price"], 250.0)
        self.assertEqual(
            trades[1]["Type"],
            TradeType.SELL,
        )
        self.assertEqual(trades[1]["Count"], 5)
        self.assertEqual(trades[1]["Price"], 260.5)

    def test_date_and_time_format(self):
        trade_add(Stock.SOXL, TradeType.BUY, 1, 100)

        trade = trades_get_all(Stock.SOXL)[0]
        datetime.strptime(trade["Date"], "%d.%m.%Y")
        datetime.strptime(trade["Time"], "%H:%M")

    def test_stocks_are_stored_separately(self):
        trade_add(Stock.SOXL, TradeType.BUY, 1, 100)
        trade_add(Stock.TSMX, TradeType.BUY, 2, 200)

        self.assertEqual(len(trades_get_all(Stock.SOXL)), 1)
        self.assertEqual(len(trades_get_all(Stock.TSMX)), 1)
        self.assertEqual(
            trades_get_all(Stock.TSMX)[0]["Count"],
            2,
        )

    def test_total_buy_averages_price(self):
        trade_add(Stock.TSMX, TradeType.BUY, 10, 250)
        trade_add(Stock.TSMX, TradeType.BUY, 10, 270)

        self.assertEqual(
            trades_total_get(Stock.TSMX),
            (20, 260.0),
        )

    def test_total_sell_keeps_price(self):
        trade_add(Stock.TSMX, TradeType.BUY, 10, 250)
        trade_add(Stock.TSMX, TradeType.SELL, 4, 300)

        self.assertEqual(
            trades_total_get(Stock.TSMX),
            (6, 250.0),
        )

    def test_total_of_each_stock(self):
        trade_add(Stock.SOXL, TradeType.BUY, 1, 100)
        trade_add(Stock.TSMX, TradeType.BUY, 2, 200)

        self.assertEqual(
            trades_total_get(Stock.SOXL),
            (1, 100.0),
        )
        self.assertEqual(
            trades_total_get(Stock.TSMX),
            (2, 200.0),
        )
        self.assertEqual(
            trades_total_get(Stock.NVDL), (0, 0.0)
        )

    def test_total_follows_edited_trades_file(self):
        # e.g. a hand edit or a Syncthing conflict
        trade_add(Stock.TSMX, TradeType.BUY, 10, 250)
        path = _trades_path(Stock.TSMX)
        with open(path) as f:
            text = f.read()
        with open(path, "w") as f:
            f.write(text.replace(",10,250", ",4,300"))

        self.assertEqual(
            trades_total_get(Stock.TSMX),
            (4, 300.0),
        )

    def test_delete_removes_row_and_keeps_ids(self):
        trade_add(Stock.TSMX, TradeType.BUY, 10, 250)
        trade_add(Stock.TSMX, TradeType.BUY, 10, 270)
        trade_add(Stock.TSMX, TradeType.SELL, 5, 300)

        self.assertTrue(trade_delete(Stock.TSMX, 2))

        trades = trades_get_all(Stock.TSMX)
        self.assertEqual([t["Id"] for t in trades], [1, 3])
        self.assertEqual(
            trades[1]["Type"],
            TradeType.SELL,
        )

    def test_delete_recalculates_total(self):
        trade_add(Stock.TSMX, TradeType.BUY, 10, 250)
        trade_add(Stock.TSMX, TradeType.BUY, 10, 270)
        trade_add(Stock.TSMX, TradeType.SELL, 5, 300)
        trade_add(Stock.SOXL, TradeType.BUY, 1, 100)

        trade_delete(Stock.TSMX, 2)

        self.assertEqual(
            trades_total_get(Stock.TSMX),
            (5, 250.0),
        )
        self.assertEqual(
            trades_total_get(Stock.SOXL),
            (1, 100.0),
        )

    def test_delete_last_trade_resets_total(self):
        trade_add(Stock.TSMX, TradeType.BUY, 10, 250)

        self.assertTrue(trade_delete(Stock.TSMX, 1))

        self.assertEqual(trades_get_all(Stock.TSMX), [])
        self.assertEqual(
            trades_total_get(Stock.TSMX), (0, 0.0)
        )

    def test_delete_unknown_id_returns_false(self):
        self.assertFalse(trade_delete(Stock.TSMX, 1))
        trade_add(Stock.TSMX, TradeType.BUY, 10, 250)

        self.assertFalse(trade_delete(Stock.TSMX, 5))
        self.assertEqual(len(trades_get_all(Stock.TSMX)), 1)

    def test_add_after_delete_does_not_reuse_id(
        self,
    ):
        trade_add(Stock.TSMX, TradeType.BUY, 10, 250)
        trade_add(Stock.TSMX, TradeType.BUY, 10, 270)
        trade_delete(Stock.TSMX, 1)
        trade_add(Stock.TSMX, TradeType.BUY, 1, 100)

        self.assertEqual(
            [t["Id"] for t in trades_get_all(Stock.TSMX)],
            [2, 3],
        )

    def test_failed_write_keeps_old_file(self):
        # and leaves no temp files
        trade_add(Stock.TSMX, TradeType.BUY, 10, 250)
        path = _trades_path(Stock.TSMX)
        with open(path, newline="") as f:
            before = f.read()

        class Boom(dict):
            def keys(self):
                raise RuntimeError("boom")

        with self.assertRaises(Exception):
            _write_csv_atomic(
                path,
                TRADE_FIELDNAMES,
                [{"Id": 1}, Boom()],
            )

        with open(path, newline="") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(
            sorted(
                f
                for f in os.listdir(storage.DB_DIR)
                if f != ".lock"
            ),
            ["tsmx_trades.csv"],
        )

    def test_rules_without_file_returns_empty(self):
        self.assertEqual(rules_get_all(), [])
        self.assertIsNone(rules_delete(1))

    def test_rules_add_and_get(self):
        self.assertEqual(
            rules_add("never buy on a gap up"), 1
        )
        self.assertEqual(rules_add("sell half at +20%"), 2)

        self.assertEqual(
            rules_get_all(),
            [
                {
                    "Id": 1,
                    "Rule": "never buy on a gap up",
                },
                {"Id": 2, "Rule": "sell half at +20%"},
            ],
        )

    def test_rules_delete_renumbers(self):
        rules_add("first")
        rules_add("second")
        rules_add("third")

        self.assertEqual(rules_delete(2), "second")

        self.assertEqual(
            rules_get_all(),
            [
                {"Id": 1, "Rule": "first"},
                {"Id": 2, "Rule": "third"},
            ],
        )
        self.assertIsNone(rules_delete(5))
        self.assertEqual(len(rules_get_all()), 2)

    def test_mail_position(self):
        self.assertIsNone(mail_position_get())
        mail_position_set("777", 42)
        self.assertEqual(mail_position_get(), ("777", 42))

    def test_watcher_status(self):
        self.assertIsNone(watcher_status_get())
        watcher_status_set(
            {
                "state": "waiting",
                "updated": "2026-10-10T12:00:00",
            }
        )
        self.assertEqual(
            watcher_status_get()["state"], "waiting"
        )

    def test_basetrades(self):
        self.assertEqual(basetrades_get_all(), [])
        self.assertFalse(basetrade_set("SOXL", 20.5, 3))
        self.assertFalse(basetrade_set("MRVU", 100.0, 10))
        # config order (MRVU before SOXL), not the
        # order they were added in
        self.assertEqual(
            [b["Stock"] for b in basetrades_get_all()],
            ["MRVU", "SOXL"],
        )
        self.assertEqual(
            basetrades_get_all()[1],
            {
                "Stock": "SOXL",
                "Price": 20.5,
                "Count": 3,
            },
        )

        # one per stock: a new one replaces the old
        self.assertTrue(basetrade_set("SOXL", 19.0, 5))
        self.assertEqual(len(basetrades_get_all()), 2)
        self.assertEqual(
            basetrades_get_all()[1]["Price"], 19.0
        )

        self.assertEqual(
            basetrade_delete("MRVU")["Count"], 10
        )
        self.assertIsNone(basetrade_delete("MRVU"))
        self.assertEqual(
            [b["Stock"] for b in basetrades_get_all()],
            ["SOXL"],
        )

    def test_alerts(self):
        self.assertEqual(alerts_get_all(), [])
        self.assertEqual(
            alert_add("basetrades", "down", 10.0), 1
        )
        self.assertEqual(
            alert_add("basetrades", "up", 2.5), 2
        )
        alert_add("gain", "down", stock="TSMX", amount=50.0)
        gain = alerts_get_all()[2]
        self.assertEqual(
            (
                gain["For"],
                gain["Stock"],
                gain["Amount"],
                gain["Percent"],
            ),
            ("gain", "TSMX", 50.0, None),
        )
        self.assertEqual(alerts_get_all()[0]["Stock"], "")
        first = alerts_get_all()[0]
        self.assertEqual(
            {k: first[k] for k in ALERT_FIELDNAMES[:4]},
            {
                "Id": 1,
                "For": "basetrades",
                "Direction": "down",
                "Percent": 10.0,
            },
        )
        alerts_status_set(
            {"state": "waiting", "past": {"1": {}}}
        )
        self.assertEqual(alert_delete(1)["Id"], 1)
        self.assertIsNone(alert_delete(1))
        self.assertEqual(
            alerts_status_get(),
            {"state": "waiting", "past": {}},
        )
        # the next Id follows the highest one
        self.assertEqual(
            alert_add("basetrades", "down", 5.0), 4
        )

    def test_ladders(self):
        self.assertEqual(ladders_get_all(), [])
        self.assertIsNone(ladder_get(1))
        self.assertEqual(
            ladder_add("SOXL", "down", 10, 100), 1
        )
        self.assertEqual(
            ladder_add("TSMX", "up", 2.5, 80.5), 2
        )

        ladder = ladder_get(2)
        self.assertEqual(ladder["Stock"], "TSMX")
        self.assertEqual(ladder["Direction"], "up")
        self.assertEqual(ladder["Step"], 2.5)
        self.assertEqual(ladder["Last"], 80.5)

        self.assertTrue(ladder_set_last(1, 90))
        self.assertFalse(ladder_set_last(5, 90))
        self.assertEqual(ladder_get(1)["Last"], 90.0)
        self.assertEqual(ladder_get(2)["Last"], 80.5)

    def test_ladder_delete(self):
        ladder_add("SOXL", "down", 10, 100)
        ladder_add("TSMX", "up", 1, 50)
        ladder_status_set(1, {"state": "stopped"})
        ladder_status_set(2, {"state": "waiting"})

        self.assertTrue(ladder_delete(1))
        self.assertFalse(ladder_delete(1))
        self.assertEqual(
            [l["Id"] for l in ladders_get_all()], [2]
        )
        self.assertIsNone(ladder_status_get(1))
        self.assertEqual(
            ladder_status_get(2)["state"], "waiting"
        )

    def test_ladder_status(self):
        self.assertIsNone(ladder_status_get(1))
        ladder_status_set(1, {"state": "waiting"})
        ladder_status_set(2, {"state": "starting"})
        self.assertEqual(
            ladder_status_get(1), {"state": "waiting"}
        )
        self.assertEqual(
            ladder_status_get(2)["state"], "starting"
        )

    def test_lock_is_reentrant(self):
        with _db_lock():
            with _db_lock():
                trade_add(
                    Stock.TSMX,
                    TradeType.BUY,
                    1,
                    100,
                )
        self.assertEqual(
            trades_total_get(Stock.TSMX),
            (1, 100.0),
        )

    @unittest.skipUnless(
        fcntl and hasattr(os, "fork"),
        "needs fork and fcntl",
    )
    def test_parallel_processes_lose_nothing(self):
        import multiprocessing

        def add_many():
            for _ in range(25):
                trade_add(
                    Stock.TSMX,
                    TradeType.BUY,
                    1,
                    100,
                )

        # the forked processes inherit the temp DB_DIR
        processes = [
            multiprocessing.get_context("fork").Process(
                target=add_many
            )
            for _ in range(4)
        ]
        for p in processes:
            p.start()
        for p in processes:
            p.join()

        trades = trades_get_all(Stock.TSMX)
        self.assertEqual(len(trades), 100)
        self.assertEqual(
            sorted(t["Id"] for t in trades),
            list(range(1, 101)),
        )
        self.assertEqual(
            trades_total_get(Stock.TSMX),
            (100, 100.0),
        )


if __name__ == "__main__":
    unittest.main()

# trade_add(Stock.SOXL, TradeType.BUY,
# 1, 100) trade_add(Stock.TSMX,
# TradeType.BUY, 2, 200)

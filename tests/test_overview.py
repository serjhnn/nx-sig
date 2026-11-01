# tests of scripts/engines/overview.py
#
#   python tests/test_overview.py
#
# the trades are real, in a temporary data folder; the
# background tasks and the device are faked

import tempfile
import unittest
from unittest import mock

import paths  # noqa: F401, scripts/ on sys.path
import config
import storage
import tasks_owner
from engines import (
    alerts,
    ladder,
    mail_broker,
    overview,
    trades,
    web,
)
from storage import Stock, TradeType


def row(task):
    return {
        "id": "-",
        "task": task,
        "pid": 1,
        "started": None,
        "state": "waiting",
        "healthy": True,
    }


class OverviewTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.patch(storage, "DB_DIR", tmp.name)
        self.patch(config, "DEMO", False)
        p = mock.patch.dict(config.DATA)
        p.start()
        self.addCleanup(p.stop)
        config.DATA.pop("fee", None)
        # no background task runs
        self.patch(ladder, "tasks", lambda: [])
        for engine in (alerts, mail_broker, web):
            self.patch(engine, "task", lambda: None)
        self.patch(tasks_owner, "owner", lambda: None)

    def patch(self, target, name, value):
        p = mock.patch.object(target, name, value)
        p.start()
        self.addCleanup(p.stop)

    def add(self, stock, kind, count, price, date, time):
        trades.add(stock, kind, count, price, date, time)

    def test_tasks(self):
        self.assertEqual(overview.tasks(), [])
        self.patch(
            ladder,
            "tasks",
            lambda: [
                row("ladder SOXL"),
                row("ladder NVDL"),
            ],
        )
        self.patch(web, "task", lambda: row("web"))
        self.patch(alerts, "task", lambda: row("alerts"))
        # the order of 'ls tasks'
        self.assertEqual(
            [t["task"] for t in overview.tasks()],
            ["ladder SOXL", "ladder NVDL", "alerts", "web"],
        )

    def test_last_trades(self):
        self.assertEqual(overview.last_trades(), [])
        buy, sell = TradeType.BUY, TradeType.SELL
        self.add(
            Stock.SOXL, buy, 10, 20, "02.09.2026", "15:00"
        )
        self.add(
            Stock.TSMX, buy, 5, 40, "01.10.2026", "09:30"
        )
        self.add(
            Stock.SOXL, sell, 4, 25, "13.10.2026", "18:02"
        )
        # the same minute: the later Id first
        self.add(
            Stock.SOXL, buy, 1, 21, "13.10.2026", "18:02"
        )
        found = overview.last_trades(3)
        self.assertEqual(
            [(t["Stock"], t["Id"]) for t in found],
            [
                (Stock.SOXL, 3),
                (Stock.SOXL, 2),
                (Stock.TSMX, 1),
            ],
        )
        self.assertEqual(found[1]["Type"], sell)
        self.assertEqual(found[1]["Count"], 4)
        self.assertEqual(len(overview.last_trades()), 4)

    def test_status(self):
        self.add(
            Stock.SOXL,
            TradeType.BUY,
            20,
            25,
            "02.09.2026",
            "15:00",
        )
        self.patch(web, "task", lambda: row("web"))
        status = overview.status({"SOXL": 30.0})
        self.assertEqual(
            sorted(status),
            sorted(
                [
                    "positions",
                    "total",
                    "tasks",
                    "mail_broker",
                    "owner",
                    "here",
                    "demo",
                    "last_trades",
                ]
            ),
        )
        (position,) = status["positions"]
        self.assertEqual(position["gain"], 100)
        self.assertEqual(status["total"], (100, 500, 20))
        self.assertEqual(status["tasks"], [row("web")])
        self.assertEqual(
            status["mail_broker"]["state"], "not started"
        )
        self.assertIsNone(status["owner"])
        self.assertFalse(status["here"])
        self.assertFalse(status["demo"])
        self.assertEqual(len(status["last_trades"]), 1)

    def test_owner(self):
        phone = {"id": "a1", "name": "phone"}
        pc = {"id": "b2", "name": "pc"}
        self.patch(tasks_owner, "owner", lambda: phone)
        self.patch(
            tasks_owner, "this_device", lambda: phone
        )
        status = overview.status({})
        self.assertEqual(status["owner"], phone)
        self.assertTrue(status["here"])
        self.patch(tasks_owner, "this_device", lambda: pc)
        self.assertFalse(overview.status({})["here"])


if __name__ == "__main__":
    unittest.main()

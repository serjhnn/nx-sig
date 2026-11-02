# tests of scripts/engines/chart.py
#
#   python tests/test_chart.py

from datetime import datetime, timedelta

import unittest
from unittest import mock

import tempfile

import paths  # noqa: F401, scripts/ on sys.path
import config
import storage
from engines import chart, prices, trades
from engines.chart import (
    chart_lines,
    parse_period,
    plot_columns,
    timeframe,
)
from storage import Stock, TradeType

START = datetime(2026, 10, 12, 9, 0)


def hourly(prices):
    return [
        (START + timedelta(hours=i), p)
        for i, p in enumerate(prices)
    ]


class ChartTest(unittest.TestCase):
    def setUp(self):
        # the layouts below are pinned with 9 rows
        patch = mock.patch.dict(
            config.DATA,
            {"terminal": {"chart_height": 9}},
        )
        patch.start()
        self.addCleanup(patch.stop)

    def test_chart_rows(self):
        self.assertEqual(config.chart_height(), 9)
        config.DATA["terminal"] = {}
        bars = hourly([10, 12, 14, 16, 18, 16, 14])
        lines = chart_lines("SOXL", (5, "5 days"), bars, 48)
        # title, rows, axis, dates, legend
        self.assertEqual(len(lines), 1 + 15 + 3)
        self.assertTrue(lines[1].startswith("18.00 |"))
        self.assertTrue(lines[15].startswith("10.00 |"))
        lines = chart_lines(
            "SOXL", (5, "5 days"), bars, 48, rows=5
        )
        self.assertEqual(len(lines), 1 + 5 + 3)

    def test_parse_period(self):
        self.assertEqual(parse_period([]), (5, "5 days"))
        self.assertEqual(
            parse_period(["period", "1", "DAY"]),
            (1, "1 day"),
        )
        self.assertEqual(
            parse_period(["period", "3", "months"]),
            (90, "3 months"),
        )
        self.assertEqual(
            parse_period(["period", "2", "week"]),
            (14, "2 weeks"),
        )
        for bad in (
            ["5"],
            ["period", "x", "days"],
            ["period", "0", "days"],
            ["period", "5", "years"],
            ["periods", "5", "days"],
            ["period", "61", "months"],
        ):
            with self.assertRaises(ValueError):
                parse_period(bad)

    def test_timeframe(self):
        # the columns of a 48 wide screen
        self.assertEqual(plot_columns(48), 36)
        self.assertEqual(timeframe(1, 36), ("15Min", "15m"))
        self.assertEqual(timeframe(5, 36), ("15Min", "15m"))
        # 20 days: 14 daily bars are too few
        self.assertEqual(timeframe(20, 40), ("1Hour", "1h"))
        self.assertEqual(timeframe(90, 36), ("1Day", "1d"))
        # a wider screen needs more bars
        self.assertEqual(timeframe(90, 88), ("1Hour", "1h"))
        self.assertEqual(
            timeframe(5 * 365, 200), ("1Day", "1d")
        )

    def test_chart(self):
        bars = hourly([10, 12, 14, 16, 18, 16, 14])
        lines = chart_lines("SOXL", (5, "5 days"), bars, 48)
        # the columns between two prices are on the
        # line between them
        self.assertEqual(
            lines,
            [
                "SOXL 5 days, 15m bars   14.00  " "+40.00%",
                "18.00 |                       ***",
                "17.00 |                    ***   ***",
                "16.00 |                 ***"
                "         ***",
                "15.00 |              ***"
                "               ***",
                "14.00 |           ***"
                "                     **",
                "13.00 |        ***",
                "12.00 |     ***",
                "11.00 |  ***",
                "10.00 |**",
                "      +" + "-" * 37,
                "       12.10",
                "* price",
            ],
        )
        for line in lines:
            self.assertLessEqual(len(line), 48)

    def test_avg_and_trades(self):
        bars = hourly([10, 12, 14, 16, 18, 16, 14])
        trades = [
            (START + timedelta(hours=1), "B", 12),
            (
                START + timedelta(hours=4, minutes=10),
                "S",
                18,
            ),
            # before the chart: left out
            (START - timedelta(days=1), "B", 5),
        ]
        lines = chart_lines(
            "SOXL",
            (5, "5 days"),
            bars,
            48,
            avg=11,
            trades=trades,
        )
        self.assertEqual(
            lines[1],
            "18.00 |                       **S",
        )
        self.assertEqual(lines[7], "12.00 |     *B*")
        self.assertEqual(
            lines[8],
            "11.00 |..***" + "." * 32 + " avg",
        )
        self.assertEqual(
            lines[-1],
            "* price  B buy  S sell  . avg buy 11.00",
        )

    def test_avg_widens_the_range(self):
        bars = hourly([10, 11])
        lines = chart_lines(
            "SOXL", (5, "5 days"), bars, 48, avg=20
        )
        self.assertTrue(lines[1].startswith("20.00 |."))
        self.assertTrue(lines[1].endswith(" avg"))
        self.assertTrue(lines[9].startswith("10.00 |*"))

    def test_many_bars_are_averaged(self):
        # 400 bars into the 36 columns of 48: the
        # labels take 6 + 2, ' avg' 4
        bars = hourly([100 + i % 7 for i in range(400)])
        lines = chart_lines(
            "SOXL", (10, "10 days"), bars, 48
        )
        plot = lines[1:10]
        self.assertEqual(max(len(l) for l in plot), 44)
        stars = sum(l.count("*") for l in plot)
        self.assertEqual(stars, 36)
        for line in lines:
            self.assertLessEqual(len(line), 48)

    def test_wider_screen(self):
        bars = hourly([100 + i % 7 for i in range(400)])
        lines = chart_lines(
            "SOXL", (10, "10 days"), bars, 100
        )
        stars = sum(l.count("*") for l in lines[1:10])
        self.assertEqual(stars, 100 - 6 - 2 - 4)
        for line in lines:
            self.assertLessEqual(len(line), 100)

    def test_one_bar_and_flat(self):
        lines = chart_lines(
            "SOXL", (1, "1 day"), hourly([5]), 48
        )
        self.assertEqual(lines[5], "5.00 |*")
        self.assertEqual(lines[0][-6:], "+0.00%")

    def test_dates(self):
        bars = [
            (START + timedelta(days=i), 10 + i)
            for i in range(90)
        ]
        lines = chart_lines(
            "SOXL", (90, "3 months"), bars, 48
        )
        self.assertEqual(
            lines[-2],
            "       12.10    02.11    24.11    16.12"
            "    07.01",
        )

    def test_colors(self):
        colors = {
            "*": "<p>",
            "B": "<b>",
            "S": "<s>",
            ".": "<a>",
            "dim": "<d>",
            "title": "<t>",
            "reset": "</>",
        }
        lines = chart_lines(
            "SOXL",
            (5, "5 days"),
            hourly([10, 12]),
            48,
            avg=11,
            colors=colors,
        )
        self.assertTrue(lines[0].startswith("<t>SOXL"))
        self.assertIn("<p>*</>", lines[1])
        self.assertIn("<a>.</>", lines[5])
        self.assertTrue(lines[5].endswith("<d> avg</>"))

    def test_thin(self):
        bars = hourly(range(10))
        self.assertEqual(chart.thin(bars, 10), bars)
        self.assertEqual(chart.thin([], 3), [])
        # pairs averaged, at the first one's time
        self.assertEqual(
            chart.thin(bars, 5),
            [
                (bars[i][0], i + 0.5)
                for i in range(0, 10, 2)
            ],
        )


class ChartDataTest(unittest.TestCase):
    """chart.data() with fake bars, the trades in a
    temp dir, no fee"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.calls = []
        self.bars = hourly([10, 12, 14])

        def get_bars(symbol, days, tf):
            self.calls.append((symbol, days, tf))
            return self.bars

        for target, name, value in (
            (storage, "DB_DIR", tmp.name),
            (prices, "get_bars", get_bars),
        ):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        # no fee in the average buy price
        p = mock.patch.dict(config.DATA)
        p.start()
        self.addCleanup(p.stop)
        config.DATA.pop("fee", None)

    def test_no_trades(self):
        found = chart.data(Stock.SOXL, 5, 60)
        self.assertEqual(
            found,
            {
                "bars": self.bars,
                "timeframe": "15Min",
                "label": "15m",
                "avg": None,
                "trades": [],
            },
        )
        self.assertEqual(self.calls, [("SOXL", 5, "15Min")])

    def test_timeframe_of_points(self):
        # the coarsest that gives about points prices
        chart.data(Stock.SOXL, 90, 60)
        chart.data(Stock.SOXL, 30, 60)
        chart.data(Stock.SOXL, 365, 200)
        self.assertEqual(
            [tf for _, _, tf in self.calls],
            ["1Day", "1Hour", "1Day"],
        )

    def test_avg_and_trades(self):
        trades.add(
            Stock.SOXL,
            TradeType.BUY,
            4,
            10,
            "12.10.2026",
            "10:00",
        )
        trades.add(
            Stock.SOXL,
            TradeType.BUY,
            4,
            14,
            "13.10.2026",
            "11:30",
        )
        trades.add(
            Stock.SOXL,
            TradeType.SELL,
            2,
            15,
            "14.10.2026",
            "15:45",
        )
        found = chart.data(Stock.SOXL, 5, 60)
        self.assertEqual(found["avg"], 12.0)
        self.assertEqual(
            found["trades"],
            [
                (datetime(2026, 10, 12, 10, 0), "B", 10.0),
                (datetime(2026, 10, 13, 11, 30), "B", 14.0),
                (datetime(2026, 10, 14, 15, 45), "S", 15.0),
            ],
        )
        # all sold: no average
        trades.add(Stock.SOXL, TradeType.SELL, 6, 16)
        self.assertIsNone(
            chart.data(Stock.SOXL, 5, 60)["avg"]
        )

    def test_stock_chart_uses_it(self):
        self.assertEqual(
            chart.stock_chart(
                Stock.SOXL, (5, "5 days"), 40
            )[0],
            "SOXL 5 days, 15m bars   14.00  +40.00%",
        )
        self.bars = []
        self.assertEqual(
            chart.stock_chart(
                Stock.SOXL, (5, "5 days"), 40
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()

# chart: a price chart for the terminal, one * per
# price, for the shell's 'chart' command
#
#   python scripts/chart.py      run the tests
#
# no network and no files: the shell passes the prices
# (trade_engine.get_bars) and the trades, and prints the
# lines this returns.
#
#   TSMX 5 days, 1h bars   71.07  -14.86%
#    83.47 |* *
#    81.92 | * ***              * *
#    77.27 |..........B..*..*.........*.** avg
#    71.07 |                                  *
#          +-----------------------------------
#           12.10    13.10    14.10    15.10
#   * price  B buy  . avg buy 78.00
#
# more prices than columns are averaged, one point per
# column; fewer are spread over the width. the price
# range includes the average buy price and the trades,
# so they are always on the chart.
#
# public functions:
#   parse_period(args)
#       (days, 'n days') of ['period', n, unit], or
#       DEFAULT_DAYS without args; ValueError if wrong
#   timeframe(days)
#       (Alpaca timeframe, label) of the bars for days
#   chart_lines(stock, period, bars, width, avg=None,
#               trades=(), colors=None)
#       the lines of the chart

import bisect
from datetime import timedelta

DEFAULT_DAYS = 5
MAX_DAYS = 5 * 365
UNITS = {
    "day": 1,
    "days": 1,
    "week": 7,
    "weeks": 7,
    "month": 30,
    "months": 30,
}
# the price rows are 0..HEIGHT
HEIGHT = 8
# room after the chart for ' avg'
AVG_ROOM = 4
# the room a date label takes, with a gap
DATE_ROOM = 9


def parse_period(args):
    """(days, text) of ['period', '5', 'days']; without
    args the default"""
    if not args:
        return DEFAULT_DAYS, f"{DEFAULT_DAYS} days"
    if (
        len(args) != 3
        or args[0].lower() != "period"
        or not args[1].isdigit()
        or int(args[1]) < 1
        or args[2].lower() not in UNITS
    ):
        raise ValueError(
            "the period is 'period <n> <days|weeks|"
            "months>', e.g. 'period 3 months'"
        )
    count = int(args[1])
    unit = args[2].lower().rstrip("s")
    days = count * UNITS[unit]
    if days > MAX_DAYS:
        raise ValueError("the longest period is 5 years")
    text = f"{count} {unit}" + ("s" if count > 1 else "")
    return days, text


def timeframe(days):
    """(Alpaca timeframe, label): hourly bars up to 10
    days, daily up to half a year, weekly beyond"""
    if days <= 10:
        return "1Hour", "1h"
    if days <= 183:
        return "1Day", "1d"
    return "1Week", "1w"


def chart_lines(
    stock,
    period,
    bars,
    width,
    avg=None,
    trades=(),
    colors=None,
):
    """the chart of bars, [(time, price)] oldest first;
    period is (days, text); avg the average buy price or
    None; trades [(time, 'B' or 'S', price)]; colors
    {'*', 'B', 'S', '.', 'dim', 'reset': escape code},
    None for plain text"""
    days, text = period
    _, bar_label = timeframe(days)
    prices = [p for _, p in bars]
    first, last = prices[0], prices[-1]
    change = (last - first) / first * 100 if first else 0
    header = (
        f"{stock} {text}, {bar_label} bars   "
        f"{last:.2f}  {change:+.2f}%"
    )

    trades = [
        t
        for t in trades
        if bars[0][0] <= t[0] <= bars[-1][0]
    ]
    values = prices + [t[2] for t in trades]
    if avg is not None:
        values.append(avg)
    low, high = min(values), max(values)
    if high - low < 1e-9:
        # a flat price: one row in the middle
        low, high = low - 1, high + 1
    label = max(len(f"{v:.2f}") for v in (low, high))
    columns = max(1, width - label - 2 - AVG_ROOM)

    points = _fit(bars, columns)
    used = max(c for c, _, _ in points) + 1
    grid = [[" "] * used for _ in range(HEIGHT + 1)]

    def row(price):
        return HEIGHT - round(
            (price - low) / (high - low) * HEIGHT
        )

    avg_row = row(avg) if avg is not None else None
    if avg_row is not None:
        grid[avg_row] = ["."] * used
    for column, _, price in points:
        grid[row(price)][column] = "*"
    times = [t for _, t, _ in points]
    for when, side, price in trades:
        # the column of the point nearest in time
        i = min(
            bisect.bisect_left(times, when), len(times) - 1
        )
        if i and when - times[i - 1] < times[i] - when:
            i -= 1
        grid[row(price)][points[i][0]] = side

    paint = _painter(colors)
    lines = [paint("title", header)]
    for r in range(HEIGHT + 1):
        value = high - (high - low) * r / HEIGHT
        cells = "".join(paint(c, c) for c in grid[r])
        line = (
            paint("dim", f"{value:>{label}.2f} |") + cells
        )
        if r == avg_row:
            line += paint("dim", " avg")
        lines.append(line.rstrip())
    lines.append(
        paint("dim", " " * (label + 1) + "+" + "-" * used)
    )
    lines.append(
        paint("dim", _dates(points, label + 2, days))
    )
    lines.append(paint("dim", _legend(avg, trades)))
    return lines


def _fit(bars, columns):
    """[(column, time, price)]: one point per column,
    the average of the bars in it, or the bars spread
    over the columns when there are fewer"""
    n = len(bars)
    if n <= columns:
        if n == 1:
            return [(0, bars[0][0], bars[0][1])]
        return [
            (round(i * (columns - 1) / (n - 1)), t, p)
            for i, (t, p) in enumerate(bars)
        ]
    points = []
    for c in range(columns):
        part = bars[
            c * n // columns : (c + 1) * n // columns
        ]
        price = sum(p for _, p in part) / len(part)
        # the time it starts, like a bar's time
        points.append((c, part[0][0], price))
    return points


def _dates(points, offset, days):
    """the date labels under the chart, as many as fit:
    where each day starts for hourly bars, evenly spread
    for longer bars"""
    used = points[-1][0] + 1
    fmt = "%d.%m" if days <= 366 else "%m.%y"
    if timeframe(days)[0] == "1Hour":
        candidates = [
            p
            for i, p in enumerate(points)
            if i == 0
            or p[1].date() != points[i - 1][1].date()
        ]
    else:
        count = max(1, used // DATE_ROOM)
        candidates = []
        for k in range(count + 1):
            column = round(k * (used - 1) / count)
            # the point at that column, or the last
            # before it
            candidates.append(
                max(
                    (p for p in points if p[0] <= column),
                    key=lambda p: p[0],
                )
            )
    line = [" "] * (offset + used + AVG_ROOM)
    taken, previous = -1, None
    for column, when, _ in candidates:
        text = f"{when:{fmt}}"
        start = offset + column
        if (
            text == previous
            or start <= taken
            or start + len(text) > len(line)
        ):
            continue
        line[start : start + len(text)] = text
        taken, previous = start + len(text), text
    return "".join(line).rstrip()


def _legend(avg, trades):
    parts = ["* price"]
    sides = {t[1] for t in trades}
    if "B" in sides:
        parts.append("B buy")
    if "S" in sides:
        parts.append("S sell")
    if avg is not None:
        parts.append(f". avg buy {avg:.2f}")
    return "  ".join(parts)


def _painter(colors):
    """paint(kind, text): text in the color of kind"""
    if not colors:
        return lambda kind, text: text

    def paint(kind, text):
        if kind == " " or kind not in colors:
            return text
        return f"{colors[kind]}{text}{colors['reset']}"

    return paint


if __name__ == "__main__":
    import unittest
    from datetime import datetime

    START = datetime(2026, 10, 12, 9, 0)

    def hourly(prices):
        return [
            (START + timedelta(hours=i), p)
            for i, p in enumerate(prices)
        ]

    class ChartTest(unittest.TestCase):
        def test_parse_period(self):
            self.assertEqual(
                parse_period([]), (5, "5 days")
            )
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
            self.assertEqual(timeframe(5), ("1Hour", "1h"))
            self.assertEqual(timeframe(10), ("1Hour", "1h"))
            self.assertEqual(timeframe(90), ("1Day", "1d"))
            self.assertEqual(
                timeframe(365), ("1Week", "1w")
            )

        def test_chart(self):
            bars = hourly([10, 12, 14, 16, 18, 16, 14])
            lines = chart_lines(
                "SOXL", (5, "5 days"), bars, 48
            )
            self.assertEqual(
                lines,
                [
                    "SOXL 5 days, 1h bars   14.00  +40.00%",
                    "18.00 |                        *",
                    "17.00 |",
                    "16.00 |                  *"
                    "           *",
                    "15.00 |",
                    "14.00 |            *"
                    "                       *",
                    "13.00 |",
                    "12.00 |      *",
                    "11.00 |",
                    "10.00 |*",
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
                lines[1], "18.00 |                        S"
            )
            self.assertEqual(lines[7], "12.00 |      B")
            self.assertEqual(
                lines[8],
                "11.00 |" + "." * 37 + " avg",
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

    unittest.main()

# chart: a price chart for the terminal, one * per
# price, for the shell's 'chart' command
#
#   python tests/test_chart.py   the tests
#
# stock_chart() is what the shell calls: it gets the
# bars (trade_engine.get_bars), the average buy price
# and the trades (storage) and draws them. the drawing
# itself, chart_lines(), has no network and no files.
#
#   TSMX 5 days, 15m bars   71.07  -14.86%
#    83.47 |* *
#    81.92 | * ***              * *
#    77.27 |..........B..*..*.........*.** avg
#    71.07 |                                  *
#          +-----------------------------------
#           12.10    13.10    14.10    15.10
#   * price  B buy  . avg buy 78.00
#
# the bars are the coarsest that still give a price
# for every column (daily, hourly or 15 minutes); more
# prices than columns are averaged, one point per
# column. when there are fewer (a short period, a
# holiday), the columns between two prices get a point
# on the straight line between them. the price range
# includes the average buy price and the trades, so
# they are always on the chart.
#
# public functions:
#   parse_period(args)
#       (days, 'n days') of ['period', n, unit], or
#       DEFAULT_DAYS without args; ValueError if wrong
#   plot_columns(width)
#       about how many columns the prices get
#   timeframe(days, columns)
#       (Alpaca timeframe, label) of the bars for days
#       that fill columns
#   stock_chart(stock, period, width, colors=None)
#       the lines of the chart of a Stock, [] when
#       there are no prices in the period; KeyError for
#       a key missing in .env, requests.RequestException
#       when the prices can't be fetched
#   chart_lines(stock, period, bars, width, avg=None,
#               trades=(), colors=None, rows=None)
#       the lines of the chart of bars, rows price rows
#       (config.chart_height() by default, config
#       "terminal" "chart_height")

import bisect
from datetime import datetime

import config
import trade_engine
from engines import trades
from engines.trades import TradeType

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
# room after the chart for ' avg'
AVG_ROOM = 4
# the room a date label takes, with a gap
DATE_ROOM = 9
# coarsest first: (Alpaca timeframe, label, about how
# many bars a calendar day has: 5 trading days a week,
# 7 hours of regular trading, 26 quarter hours)
TIMEFRAMES = [
    ("1Day", "1d", 5 / 7),
    ("1Hour", "1h", 5),
    ("15Min", "15m", 18),
]
# the price labels, e.g. '164.18', for plot_columns
LABEL_ROOM = 6


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


def plot_columns(width):
    """about how many columns the prices get on a
    screen width wide"""
    return max(1, width - LABEL_ROOM - 2 - AVG_ROOM)


def timeframe(days, columns):
    """(Alpaca timeframe, label) of the coarsest bars
    that give days at least one price per column; the
    finest when none does"""
    for name, label, per_day in TIMEFRAMES:
        if days * per_day >= columns:
            return name, label
    return TIMEFRAMES[-1][:2]


def stock_chart(stock, period, width, colors=None):
    """the chart of stock over period, (days, text),
    with its average buy price and trades"""
    days, _ = period
    tf, _ = timeframe(days, plot_columns(width))
    bars = trade_engine.get_bars(stock.name, days, tf)
    if not bars:
        return []
    count, avg = trades.total(stock)
    return chart_lines(
        stock.name,
        period,
        bars,
        width,
        avg=avg if count > 0 else None,
        trades=_trades(stock),
        colors=colors,
    )


def _trades(stock):
    """[(time, 'B' or 'S', price)] of the stock's
    trades"""
    found = []
    for t in trades.get_all(stock):
        try:
            when = datetime.strptime(
                f"{t['Date']} {t['Time']}", "%d.%m.%Y %H:%M"
            )
        except ValueError:
            continue
        side = "B" if t["Type"] == TradeType.BUY else "S"
        found.append((when, side, t["Price"]))
    return found


def chart_lines(
    stock,
    period,
    bars,
    width,
    avg=None,
    trades=(),
    colors=None,
    rows=None,
):
    """the chart of bars, [(time, price)] oldest first;
    period is (days, text); avg the average buy price or
    None; trades [(time, 'B' or 'S', price)]; colors
    {'*', 'B', 'S', '.', 'dim', 'reset': escape code},
    None for plain text; rows the number of price
    rows, config.chart_height() by default"""
    # the price rows are 0..height
    height = (rows or config.chart_height()) - 1
    days, text = period
    tf, bar_label = timeframe(days, plot_columns(width))
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
    grid = [[" "] * used for _ in range(height + 1)]

    def row(price):
        return height - round(
            (price - low) / (high - low) * height
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
    for r in range(height + 1):
        value = high - (high - low) * r / height
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
        paint("dim", _dates(points, label + 2, days, tf))
    )
    lines.append(paint("dim", _legend(avg, trades)))
    return lines


def _fit(bars, columns):
    """[(column, time, price)]: one point per column,
    the average of the bars in it; fewer bars are spread
    over the columns, the ones between two bars on the
    straight line between them"""
    n = len(bars)
    if n <= columns:
        if n == 1:
            return [(0, bars[0][0], bars[0][1])]
        spread = [
            (round(i * (columns - 1) / (n - 1)), t, p)
            for i, (t, p) in enumerate(bars)
        ]
        points = []
        for (c0, t0, p0), (c1, t1, p1) in zip(
            spread, spread[1:]
        ):
            for c in range(c0, c1):
                f = (c - c0) / (c1 - c0)
                points.append(
                    (
                        c,
                        t0 + (t1 - t0) * f,
                        p0 + (p1 - p0) * f,
                    )
                )
        points.append(spread[-1])
        return points
    points = []
    for c in range(columns):
        part = bars[
            c * n // columns : (c + 1) * n // columns
        ]
        price = sum(p for _, p in part) / len(part)
        # the time it starts, like a bar's time
        points.append((c, part[0][0], price))
    return points


def _dates(points, offset, days, tf):
    """the date labels under the chart, as many as fit:
    where each day starts for hourly bars, evenly spread
    for the others; times for 15 minute bars"""
    used = points[-1][0] + 1
    fmt = "%d.%m" if days <= 366 else "%m.%y"
    if tf == "15Min":
        fmt = "%H:%M" if days <= 1 else "%d.%m"
    if tf == "1Hour" or (tf == "15Min" and days > 1):
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

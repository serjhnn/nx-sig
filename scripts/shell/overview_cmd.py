# overview_cmd: the commands that span the features
#
#   status      held positions with gain/loss and the
#               mail watcher
#   xtop [sec]  live gain/loss with Telegram alerts
#   ps          running background tasks
#
# OverviewCmd is mixed into NxSigShell: these are
# commands of their own, not kinds of data

import queue
import sys
import threading
from datetime import datetime

from trade_engine import config, start_polling
from telegram_notify import (
    is_configured as telegram_configured,
    notify as telegram_send,
)
from shell.ui import (
    BOLD,
    BUY_COLOR,
    COUNT_COLOR,
    DATE_COLOR,
    DIM,
    PRICE_COLOR,
    RESET,
    SELL_COLOR,
    TOTAL_STOCK_COLOR,
    WIDTH,
    XTOP_SEP,
    _column_sep,
    _fetch_prices,
    _gain_color,
    _held_positions,
    _print_error,
    _print_wrapped,
    _supports_color,
)
from shell.mail_cmd import _print_watcher_status


class OverviewCmd:
    # ---------------- status ----------------

    def do_status(self, arg):
        """
        status
            show all held positions with count,
            average buy price, current price and
            state: gain/loss in money,
            count * (price - avg price),
            and whether order_watcher.py is running
        """
        if arg.strip():
            _print_wrapped("usage: status")
            return

        positions = _held_positions()
        if not positions:
            _print_wrapped("no stocks held")
            _print_watcher_status()
            return

        prices = _fetch_prices()

        color = _supports_color()
        column_sep = _column_sep(color)
        header_cols = [
            f"{'Name':<5}",
            f"{'Count':>5}",
            f"{'Avg Price':>9}",
            f"{'Price':>8}",
            f"{'State':>9}",
        ]
        if color:
            header_cols = [
                f"{DIM}{col}{RESET}" for col in header_cols
            ]
        separator = "-" * WIDTH
        print()
        print(column_sep.join(header_cols))
        print(
            f"{DIM}{separator}{RESET}"
            if color
            else separator
        )
        for stock, total_count, avg_price in positions:
            name = f"{stock.name:<5}"
            count = f"{total_count:>5}"
            avg = f"{avg_price:>9.2f}"
            price = f"{'-':>8}"
            state = f"{'-':>9}"
            state_color = DIM
            if stock.name in prices:
                current = prices[stock.name]
                gain = (
                    total_count * current
                    - total_count * avg_price
                )
                price = f"{current:>8.2f}"
                state = f"{gain:>+9.2f}"
                state_color = (
                    BUY_COLOR
                    if gain > 0
                    else SELL_COLOR if gain < 0 else DIM
                )
            if color:
                name = (
                    f"{BOLD}{TOTAL_STOCK_COLOR}"
                    f"{name}{RESET}"
                )
                count = f"{COUNT_COLOR}{count}{RESET}"
                avg = f"{PRICE_COLOR}{avg}{RESET}"
                price = f"{PRICE_COLOR}{price}{RESET}"
                state = f"{state_color}{state}{RESET}"
            print(
                column_sep.join(
                    [name, count, avg, price, state]
                )
            )
        print(
            f"{DIM}{separator}{RESET}"
            if color
            else separator
        )
        _print_watcher_status()
        print()

    # ---------------- xtop ----------------

    def do_xtop(self, arg):
        """
        xtop [sec]
            live gain/loss of the stocks you hold:
            quantity, average buy price, current
            price, gain and gain %, updated every
            5 seconds or every <sec> seconds,
            e.g. 'xtop 10'.
            Ctrl+C returns to the shell
        """
        args = arg.split()
        if len(args) > 1:
            _print_wrapped("usage: xtop [sec]")
            return
        interval = 5.0
        if args:
            try:
                interval = float(args[0])
            except ValueError:
                interval = 0
            if interval < 1:
                _print_error(
                    "error: seconds must be a number >= "
                    f"1, got '{args[0]}'"
                )
                return

        if not _held_positions():
            _print_wrapped("no stocks held")
            return

        # the polling thread only queues results, all
        # drawing happens here in the main thread
        updates = queue.Queue()
        stop = start_polling(
            interval,
            on_update=lambda prices: updates.put(
                ("prices", prices)
            ),
            on_error=lambda e: updates.put(("error", e)),
        )
        alerts = _GainAlerts(
            GAIN_ALERT,
            GAIN_ALERT_PCT,
            report=lambda text: updates.put(("note", text)),
        )

        color = _supports_color()
        prices, error, updated = {}, None, None
        drawn = 0
        if color:
            print(
                "\033[?25l", end=""
            )  # hide the cursor while redrawing
        try:
            print()
            drawn = _draw_xtop(
                _xtop_lines(
                    prices,
                    error,
                    updated,
                    interval,
                    color,
                    alerts.lines(),
                ),
                drawn,
                color,
            )
            while True:
                try:
                    # short timeout so Ctrl+C is handled
                    # promptly, also on Windows
                    kind, value = updates.get(timeout=0.2)
                except queue.Empty:
                    continue
                if kind == "prices":
                    prices, error = value, None
                    updated = datetime.now()
                    alerts.check(_xtop_rows(prices))
                elif kind == "error":
                    error = value
                else:
                    alerts.note = value
                drawn = _draw_xtop(
                    _xtop_lines(
                        prices,
                        error,
                        updated,
                        interval,
                        color,
                        alerts.lines(),
                    ),
                    drawn,
                    color,
                )
        except KeyboardInterrupt:
            pass
        finally:
            stop.set()
            if color:
                print("\033[?25h", end="")
            print()

    def do_ps(self, arg):
        """
        ps
            list the background tasks that are
            running as their own process, with
            their pid, start time and state
        """
        if arg.strip():
            _print_wrapped("usage: ps")
            return
        # every module with background tasks adds its
        # rows
        tasks = [
            task
            for module in self.objects.values()
            for task in module.tasks()
        ]
        if not tasks:
            _print_wrapped("no background tasks running")
            return
        _print_tasks(tasks)


# a Telegram alert is sent when a held stock's gain
# reaches this amount (config "gain_alert", default +100)
# or this % (config "gain_alert_pct", default +10)
GAIN_ALERT = config.get("gain_alert", 100)
GAIN_ALERT_PCT = config.get("gain_alert_pct", 10)


def _xtop_rows(prices):
    """one dict per held stock: stock, count, avg, price,
    gain (count * (price - avg)) and pct; price, gain and
    pct are None without a price"""
    rows = []
    # re-read every time: the order watcher may record
    # a trade while xtop runs
    for stock, count, avg_price in _held_positions():
        row = {
            "stock": stock,
            "count": count,
            "avg": avg_price,
            "price": None,
            "gain": None,
            "pct": None,
            "cost": abs(count) * avg_price,
        }
        if stock.name in prices:
            row["price"] = prices[stock.name]
            row["gain"] = count * (row["price"] - avg_price)
            if row["cost"]:
                row["pct"] = row["gain"] / row["cost"] * 100
        rows.append(row)
    return rows


class _GainAlerts:
    """send a Telegram message when a stock's gain reaches
    the amount or the % threshold; each threshold fires
    again only after the gain has gone below it"""

    def __init__(self, threshold, threshold_pct, report):
        # (row key, threshold) of each alert
        self.thresholds = [
            ("gain", threshold),
            ("pct", threshold_pct),
        ]
        self.enabled = telegram_configured()
        # report(text) shows a result line in xtop
        self.report = report
        self.note = None
        # (stock name, row key) above their threshold
        self._above = set()

    def check(self, rows):
        for row in rows:
            name = row["stock"].name
            reached = False
            for key, threshold in self.thresholds:
                if row[key] is None:
                    continue
                if row[key] < threshold:
                    self._above.discard((name, key))
                elif (name, key) not in self._above:
                    self._above.add((name, key))
                    reached = True
            # one message, also when both are reached
            if reached and self.enabled:
                self._send(row)

    def _send(self, row):
        gain = f"{row['gain']:+.2f}"
        pct = (
            ""
            if row["pct"] is None
            else (f" ({row['pct']:+.2f}%)")
        )
        text = f"{row['stock'].name} gain {gain}{pct}"
        short = f"{row['stock'].name} {gain}{pct}"

        def send():
            # in a thread, so a slow Telegram doesn't stop
            # the table from updating
            try:
                telegram_send(text)
                now = datetime.now()
                self.report(
                    f"alert {now:%H:%M} sent: {short}"
                )
            except Exception as e:
                self.report(f"alert not sent: {e}")

        threading.Thread(target=send, daemon=True).start()

    def lines(self):
        """footer lines for the xtop table"""
        if not self.enabled:
            return ["alerts off: TOKEN/CHAT_ID not in .env"]
        amount = f"{self.thresholds[0][1]:+g}"
        pct = f"{self.thresholds[1][1]:+g}%"
        lines = [
            f"alerts: gain >= {amount} or {pct} -> Telegram"
        ]
        if self.note:
            lines.append(self.note)
        return lines


def _xtop_lines(
    prices, error, updated, interval, color, notes=()
):
    """build the lines of the 'xtop' table: gain/loss of
    each held stock at its current price"""
    # six columns don't fit 48 characters with ' | '
    # between them, so they are separated by a space
    column_sep = XTOP_SEP
    header_cols = [
        f"{'Name':<5}",
        f"{'Qty':>4}",
        f"{'Avg':>8}",
        f"{'Price':>8}",
        f"{'Gain':>9}",
        f"{'Gain %':>8}",
    ]
    if color:
        header_cols = [
            f"{DIM}{col}{RESET}" for col in header_cols
        ]
    separator = "-" * WIDTH
    separator = (
        f"{DIM}{separator}{RESET}" if color else separator
    )
    lines = [column_sep.join(header_cols), separator]

    total_gain = total_cost = 0.0
    for row in _xtop_rows(prices):
        name = f"{row['stock'].name:<5}"
        qty = f"{row['count']:>4}"
        avg = f"{row['avg']:>8.2f}"
        price = f"{'-':>8}"
        gain = f"{'-':>9}"
        gain_pct = f"{'-':>8}"
        gain_color = DIM
        if row["gain"] is not None:
            price = f"{row['price']:>8.2f}"
            gain = f"{row['gain']:>+9.2f}"
            if row["pct"] is not None:
                gain_pct = f"{row['pct']:>+7.2f}%"
            gain_color = _gain_color(row["gain"])
            total_gain += row["gain"]
            total_cost += row["cost"]
        if color:
            name = (
                f"{BOLD}{TOTAL_STOCK_COLOR}"
                f"{name}{RESET}"
            )
            qty = f"{COUNT_COLOR}{qty}{RESET}"
            avg = f"{PRICE_COLOR}{avg}{RESET}"
            price = f"{PRICE_COLOR}{price}{RESET}"
            gain = f"{gain_color}{gain}{RESET}"
            gain_pct = f"{gain_color}{gain_pct}{RESET}"
        lines.append(
            column_sep.join(
                [name, qty, avg, price, gain, gain_pct]
            )
        )

    lines.append(separator)
    lines.append(
        _xtop_total_line(total_gain, total_cost, color)
    )
    if updated is None:
        status = "waiting for prices..."
    else:
        status = (
            f"updated {updated:%H:%M:%S}, every "
            f"{interval:g}s, Ctrl+C to stop"
        )
    lines.append(
        f"{DIM}{status}{RESET}" if color else status
    )
    for note in notes:
        note = note[:WIDTH]
        lines.append(
            f"{DIM}{note}{RESET}" if color else note
        )
    if error is not None:
        # keep the error on one line so the redraw line
        # count stays stable
        lines.append(f"error: {error}"[:WIDTH])
    return lines


def _xtop_total_line(total_gain, total_cost, color):
    """'total' row under the table: the gain of all held
    stocks that have a price, and its % of their cost"""
    label = f"{'total':<5}"
    # the empty Qty, Avg and Price columns
    blank = " " * (1 + 4 + 1 + 8 + 1 + 8 + 1)
    if not total_cost:
        line = label + blank + f"{'-':>9}"
        return f"{DIM}{line}{RESET}" if color else line
    gain = f"{total_gain:>+9.2f}"
    pct = total_gain / total_cost * 100
    gain_pct = f"{pct:>+7.2f}%"
    if color:
        gain_color = _gain_color(total_gain)
        label = f"{DIM}{label}{RESET}"
        gain = f"{BOLD}{gain_color}{gain}{RESET}"
        gain_pct = f"{BOLD}{gain_color}{gain_pct}{RESET}"
    return label + blank + gain + XTOP_SEP + gain_pct


def _draw_xtop(lines, drawn, color):
    """draw the 'xtop' table over the previously drawn one,
    return the number of lines drawn"""
    if color and drawn:
        # move the cursor up to the first line of the old
        # table and clear everything below
        sys.stdout.write(f"\033[{drawn}F\033[J")
    elif not color and drawn:
        print()
    print("\n".join(lines))
    sys.stdout.flush()
    return len(lines)


def _print_tasks(tasks):
    """the ps table: Id, Task, PID, Started, State"""
    color = _supports_color()
    sep = "  "
    header = sep.join(
        [
            f"{'Id':>2}",
            f"{'Task':<11}",
            f"{'PID':>7}",
            f"{'Started':<11}",
            f"{'State':<9}",
        ]
    )
    separator = "-" * WIDTH
    print()
    if color:
        print(f"{DIM}{header}{RESET}")
        print(f"{DIM}{separator}{RESET}")
    else:
        print(header)
        print(separator)
    for t in tasks:
        started = (
            f"{t['started']:%d.%m %H:%M}"
            if t["started"]
            else "-"
        )
        cols = [
            f"{t['id']:>2}",
            f"{t['task']:<11.11}",
            f"{t['pid']:>7}",
            f"{started:<11}",
            f"{t['state']:<9.9}",
        ]
        if color:
            state_color = (
                BUY_COLOR if t["healthy"] else SELL_COLOR
            )
            cols = [
                f"{DIM}{cols[0]}{RESET}",
                f"{BOLD}{TOTAL_STOCK_COLOR}"
                f"{cols[1]}{RESET}",
                f"{COUNT_COLOR}{cols[2]}{RESET}",
                f"{DATE_COLOR}{cols[3]}{RESET}",
                f"{state_color}{cols[4]}{RESET}",
            ]
        print(sep.join(cols))
    print()

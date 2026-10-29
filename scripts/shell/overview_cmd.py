# overview_cmd: the commands that span the features
#
#   status      held positions with gain/loss, the
#               mail broker and the device of the
#               background tasks
#   xtop [sec] [al]
#               live gain/loss, with al the gain
#               alerts (alert_cmd.py) below the table
#
# OverviewCmd is mixed into NxSigShell: these are
# commands of their own, not kinds of data

import queue
import sys
from datetime import datetime

import config
from engines.prices import start_polling
from shell.ui import (
    padded,
    print_table,
    rule,
    BOLD,
    BUY_COLOR,
    COUNT_COLOR,
    DIM,
    PRICE_COLOR,
    RESET,
    SELL_COLOR,
    TOTAL_STOCK_COLOR,
    width,
    space_separator,
    column_separator,
    fetch_prices,
    color_for_gain,
    key_reader,
    held_positions,
    print_error,
    print_wrapped,
    supports_color,
)
from shell.alert_cmd import gain_alert_lines
from shell.demo_cmd import demo_status
from shell.mail_cmd import print_watcher_status
from shell.tasks_cmd import print_owner


class OverviewCmd:
    # ---------------- status ----------------

    def do_status(self, arg):
        """
        status
            show all held positions with count,
            average buy price, current price and
            state: gain/loss in money,
            count * (price - avg price),
            and whether the mail broker is running
            and which device runs the background
            tasks
        """
        if arg.strip():
            print_wrapped("usage: status")
            return

        positions = held_positions()
        if not positions:
            print_wrapped("no stocks held")
            print_watcher_status()
            if config.demo():
                demo_status()
            print_owner()
            return

        prices = fetch_prices()

        color = supports_color()
        column_sep = column_separator(color, 5)
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
        header = column_sep.join(header_cols)
        separator = rule(header)
        lines = [
            header,
            (
                f"{DIM}{separator}{RESET}"
                if color
                else separator
            ),
        ]
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
            lines.append(
                column_sep.join(
                    [name, count, avg, price, state]
                )
            )
        lines.append(lines[1])
        print()
        print_table(lines)
        print_watcher_status()
        if config.demo():
            demo_status()
        print_owner()
        print()

    # ---------------- xtop ----------------

    def do_xtop(self, arg):
        """
        xtop [sec] [al]
            live gain/loss of the stocks you hold:
            quantity, average buy price, current
            price, gain and gain %, updated every
            5 seconds or every <sec> seconds,
            e.g. 'xtop 10'; with al, below it the
            gain alerts and the stocks in alert
            (see 'help add alert'). q returns to
            the shell
        """
        args = arg.lower().split()
        show_alerts = "al" in args
        if show_alerts:
            args.remove("al")
        if len(args) > 1 or "al" in args:
            print_wrapped("usage: xtop [sec] [al]")
            return
        interval = 5.0
        if args:
            try:
                interval = float(args[0])
            except ValueError:
                interval = 0
            if interval < 1:
                print_error(
                    "error: seconds must be a number >= "
                    f"1, got '{args[0]}'"
                )
                return

        if not held_positions():
            print_wrapped("no stocks held")
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

        def notes(prices):
            if not show_alerts:
                return []
            return gain_alert_lines(prices)

        color = supports_color()
        prices, error, updated = {}, None, None
        drawn = 0
        if color:
            print(
                "\033[?25l", end=""
            )  # hide the cursor while redrawing
        try:
            with key_reader() as read_key:
                print()
                drawn = _draw_xtop(
                    _xtop_lines(
                        prices,
                        error,
                        updated,
                        interval,
                        color,
                        notes(prices),
                    ),
                    drawn,
                    color,
                )
                while True:
                    if read_key() in ("q", "Q"):
                        break
                    try:
                        # short timeout so q and Ctrl+C are
                        # handled promptly, also on Windows
                        kind, value = updates.get(
                            timeout=0.2
                        )
                    except queue.Empty:
                        continue
                    if kind == "prices":
                        prices, error = value, None
                        updated = datetime.now()
                    else:
                        error = value
                    drawn = _draw_xtop(
                        _xtop_lines(
                            prices,
                            error,
                            updated,
                            interval,
                            color,
                            notes(prices),
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


def _xtop_rows(prices):
    """one dict per held stock: stock, count, avg, price,
    gain (count * (price - avg)) and pct; price, gain and
    pct are None without a price"""
    rows = []
    # re-read every time: the order watcher may record
    # a trade while xtop runs
    for stock, count, avg_price in held_positions():
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


def _xtop_lines(
    prices, error, updated, interval, color, notes=()
):
    """build the lines of the 'xtop' table: gain/loss of
    each held stock at its current price; notes are
    lines below it, colored and fitted to width()"""
    # six columns don't fit 48 characters with ' | '
    # between them, so they are separated by a space
    # (more on a wider screen)
    column_sep = space_separator(6, 1)
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
    separator = rule(column_sep.join(header_cols))
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
            gain_color = color_for_gain(row["gain"])
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
    # the lines below fill the width, not padded
    lines = padded(lines)
    if updated is None:
        status = "waiting for prices..."
    else:
        status = (
            f"updated {updated:%H:%M:%S}, every "
            f"{interval:g}s, q to stop"
        )
    lines.append(
        f"{DIM}{status}{RESET}" if color else status
    )
    lines += notes
    if error is not None:
        # keep the error on one line so the redraw line
        # count stays stable
        lines.append(f"error: {error}"[: width()])
    return lines


def _xtop_total_line(total_gain, total_cost, color):
    """'total' row under the table: the gain of all held
    stocks that have a price, and its % of their cost"""
    label = f"{'total':<5}"
    sep = space_separator(6, 1)
    # the empty Qty, Avg and Price columns
    blank = sep.join(["", " " * 4, " " * 8, " " * 8, ""])
    if not total_cost:
        line = label + blank + f"{'-':>9}"
        return f"{DIM}{line}{RESET}" if color else line
    gain = f"{total_gain:>+9.2f}"
    pct = total_gain / total_cost * 100
    gain_pct = f"{pct:>+7.2f}%"
    if color:
        gain_color = color_for_gain(total_gain)
        label = f"{DIM}{label}{RESET}"
        gain = f"{BOLD}{gain_color}{gain}{RESET}"
        gain_pct = f"{BOLD}{gain_color}{gain_pct}{RESET}"
    return label + blank + gain + sep + gain_pct


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

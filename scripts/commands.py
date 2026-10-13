# interactive shell for nX-sig, started with ./nxshell
#
# commands (tr is short for transactions):
#   tr add <stock> <buy|sell> <count> <price>
#   tr get <stock>
#   tr del-last <stock>
#   tr del <stock> <index>  (disabled, use 'tr del-last')
#   ls <stock>      alias for 'tr get <stock>'
#   ls              totals and growth % of held stocks
#   status          positions with current price and
#                   gain/loss
#   xtop [sec]      live gain/loss of held stocks,
#                   updated every 5 or <sec> seconds
#   rules [add <rule>/delete <id>]
#                   personal rules
#   strategy [run/stop/list/get]
#                   not implemented yet
#   help, exit, quit, q

import cmd
import inspect
import os
import queue
import sys
import textwrap
import threading
from datetime import datetime

from storage import (
    Stock,
    TransactionType,
    transactions_add_one,
    transactions_delete,
    transactions_get_all,
    transactions_total_get,
    rules_add,
    rules_delete,
    rules_get_all,
    watcher_status_get,
)
from trade_engine import (
    config,
    get_latest_prices,
    start_polling,
)
from telegram_notify import (
    is_configured as telegram_configured,
    notify as telegram_send,
)

LOGO = r"""
         __  __             _
   _ __  \ \/ /       ___  (_)  __ _
  | '_ \  \  /  ____ / __| | | / _` |
  | | | | /  \ |____|\__ \ | || (_| |
  |_| |_|/_/\_\      |___/ |_| \__, |
                               |___/
"""
SUBTITLE = (
    "  nX-sig shell. 'help' for commands, 'q' to quit"
)

# all output is kept within the width of the 'tr get' table
# so it fits a mobile screen
WIDTH = 48

# 256-color gradient, one per logo line, top to bottom:
# light blue -> dark green
LOGO_COLORS = [
    f"\033[38;5;{c}m" for c in (117, 80, 43, 36, 29, 22)
]
DIM = "\033[2m"
DATE_COLOR = "\033[38;5;30m"
COUNT_COLOR = "\033[38;5;96m"
TOTAL_COUNT_COLOR = "\033[38;5;28m"
PRICE_COLOR = "\033[38;5;136m"
TOTAL_STOCK_COLOR = "\033[38;5;117m"
BUY_COLOR = "\033[38;5;28m"
SELL_COLOR = "\033[38;5;124m"
BOLD = "\033[1m"
RESET = "\033[0m"
PROMPT_COLOR = LOGO_COLORS[2]  # teal from the logo gradient
RULE_COLOR = LOGO_COLORS[
    -1
]  # dark green, the last color of the logo gradient


def _supports_color():
    if not sys.stdout.isatty() or os.environ.get(
        "NO_COLOR"
    ):
        return False
    if os.name == "nt":
        # enables ANSI escape codes in the Windows console
        os.system("")
    return True


def _banner():
    if not _supports_color():
        return f"{LOGO}\n{SUBTITLE}\n"
    lines = LOGO.strip("\n").split("\n")
    last = len(LOGO_COLORS) - 1
    colored = [
        f"{LOGO_COLORS[min(i, last)]}{line}{RESET}"
        for i, line in enumerate(lines)
    ]
    return (
        "\n"
        + "\n".join(colored)
        + f"\n\n{DIM}{SUBTITLE}{RESET}\n"
    )


HELP = """
commands:
  tr add <stock> <buy|sell> <count> <price>
      record a transaction
  tr get <stock>, ls <stock>
      show transactions and total
  ls
      totals of all stocks held, with growth %
  tr del-last <stock>
      delete the last transaction
  status
      positions with current price and gain/loss
  xtop [sec]
      live gain/loss of held stocks, updated
      every 5 or <sec> seconds
  rules
      show personal rules
  rules add <rule>, rules delete <id>
      add or delete a personal rule
  strategy [run/stop/list/get]
      not implemented yet
  help [command]
      show help
  exit, quit, q
      leave the shell

  tr is short for transactions
"""


class NxSigShell(cmd.Cmd):
    intro = _banner()
    # \001/\002 tell readline the escape codes are
    # zero-width so line editing stays aligned
    prompt = (
        f"\001{PROMPT_COLOR}\002nX-sig>\001{RESET}\002 "
        if _supports_color()
        else "nX-sig> "
    )

    def preloop(self):
        # keep '-' inside words so 'del-last' completes as
        # one word
        try:
            import readline

            readline.set_completer_delims(
                readline.get_completer_delims().replace(
                    "-", ""
                )
            )
        except ImportError:
            pass

    # ---------------- transactions ----------------

    def do_transactions(self, arg):
        """
        tr add <stock> <buy|sell> <count> <price>
            record a transaction,
            e.g. 'tr add NVDA buy 10 120.5'
        tr get <stock>
            show all transactions and the current
            total for a stock
        tr del-last <stock>
            show the last transaction of a stock
            and delete it after confirmation,
            e.g. 'tr del-last NVDA'
        tr is short for transactions
        """
        args = arg.split()
        if not args:
            _print_wrapped(
                "usage: tr [add/get/del-last] ..."
            )
            return

        sub, rest = args[0].lower(), args[1:]
        if sub == "add":
            self._transactions_add_one(rest)
        elif sub == "get":
            self._transaction_get(rest)
        elif sub == "del-last":
            self._transactions_delete_last(rest)
        # 'tr del <stock> <index>' is disabled in favour of
        # 'tr del-last <stock>'
        # elif sub == "del":
        #     self._transactions_delete(rest)
        else:
            _print_error(
                f"unknown subcommand '{sub}', expected "
                "add/get/del-last"
            )

    def _transactions_add_one(self, args):
        if len(args) != 4:
            _print_wrapped(
                "usage: tr add <stock> <buy|sell> <count> "
                "<price>"
            )
            return
        try:
            stock = _parse_stock(args[0])
            transaction_type = _parse_transaction_type(
                args[1]
            )
            count = int(args[2])
            price = float(args[3])
        except ValueError as e:
            _print_error(f"error: {e}")
            return
        if count <= 0 or price <= 0:
            _print_error(
                "error: count and price must be positive"
            )
            return

        transactions_add_one(
            stock, transaction_type, count, price
        )
        _print_wrapped(
            f"added {transaction_type.name} {count} "
            f"{stock.name} @ {price}"
        )

    def _transactions_delete(self, args):
        if len(args) != 2:
            _print_wrapped("usage: tr del <stock> <index>")
            return
        try:
            stock = _parse_stock(args[0])
        except ValueError as e:
            _print_error(f"error: {e}")
            return
        if not args[1].isdigit():
            _print_error(
                "error: index must be a number, got "
                f"'{args[1]}'"
            )
            return
        index = int(args[1])

        transaction = next(
            (
                t
                for t in transactions_get_all(stock)
                if t["Index"] == index
            ),
            None,
        )
        if transaction is None:
            _print_error(
                f"error: no {stock.name} transaction with "
                f"Id {index}"
            )
            return
        self._confirm_and_delete(stock, transaction)

    def _transactions_delete_last(self, args):
        if len(args) != 1:
            _print_wrapped("usage: tr del-last <stock>")
            return
        try:
            stock = _parse_stock(args[0])
        except ValueError as e:
            _print_error(f"error: {e}")
            return

        transactions = transactions_get_all(stock)
        if not transactions:
            _print_wrapped(
                f"no transactions for {stock.name}"
            )
            return
        # transactions are appended, so the last row is the
        # latest one
        self._confirm_and_delete(stock, transactions[-1])

    def _confirm_and_delete(self, stock, transaction):
        """show a transaction, ask for confirmation and
        delete it"""
        index = transaction["Index"]
        color = _supports_color()
        print()
        _print_transactions_header(color)
        _print_transaction_row(transaction, color)
        print()
        try:
            answer = input(
                f"delete this {stock.name} transaction? "
                "[y/N] "
            )
        except (EOFError, KeyboardInterrupt):
            # Ctrl+D / Ctrl+C at the prompt cancels instead
            # of leaving the shell
            answer = ""
            print()
        if answer.strip().lower() not in ("y", "yes"):
            _print_wrapped("cancelled")
            return

        transactions_delete(stock, index)
        _print_wrapped(
            f"deleted {stock.name} transaction {index}"
        )

    def _transaction_get(self, args):
        if len(args) != 1:
            _print_wrapped("usage: tr get <stock>")
            return
        try:
            stock = _parse_stock(args[0])
        except ValueError as e:
            _print_error(f"error: {e}")
            return

        transactions = transactions_get_all(stock)
        if not transactions:
            _print_wrapped(
                f"no transactions for {stock.name}"
            )
            return

        color = _supports_color()
        print()
        _print_transactions_header(color)
        for t in transactions:
            _print_transaction_row(t, color)
        separator = "-" * WIDTH

        print(
            f"{DIM}{separator}{RESET}"
            if color
            else separator
        )
        _print_total(stock, color)
        print()

    def complete_transactions(
        self, text, line, begidx, endidx
    ):
        options = [
            ["add", "get", "del-last"],
            [s.name for s in Stock],
        ]
        # only 'add' takes a transaction type after the
        # stock name
        args = line.split()
        if len(args) > 1 and args[1].lower() == "add":
            options.append(
                [t.name.lower() for t in TransactionType]
            )
        return _complete(text, line, options)

    do_tr = do_transactions
    complete_tr = complete_transactions

    def do_ls(self, arg):
        """
        ls <stock>
            alias for 'transactions get <stock>'
        ls
            show count, average buy price and
            total price of all stocks held, and
            growth %: how much the current price
            is above (or below) the average price
        """
        args = arg.split()
        if not args:
            self._totals_all()
            return
        self._transaction_get(args)

    def _totals_all(self):
        totals = _held_positions()
        if not totals:
            _print_wrapped("no stocks held")
            return
        prices = _fetch_prices()

        color = _supports_color()
        column_sep = _column_sep(color)
        header_cols = [
            f"{'Name':<5}",
            f"{'Count':>5}",
            f"{'Avg Price':>9}",
            f"{'Total':>8}",
            f"{'Growth %':>8}",
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
        for stock, total_count, avg_price in totals:
            name = f"{stock.name:<5}"
            count = f"{total_count:>5}"
            avg = f"{avg_price:>9.2f}"
            total = f"{total_count * avg_price:>8.2f}"
            growth = f"{'-':>8}"
            growth_color = DIM
            current = prices.get(stock.name)
            if current is not None and avg_price > 0:
                pct = (
                    (current - avg_price) / avg_price * 100
                )
                growth = f"{pct:>+7.2f}%"
                growth_color = _gain_color(pct)
            if color:
                name = (
                    f"{BOLD}{TOTAL_STOCK_COLOR}"
                    f"{name}{RESET}"
                )
                count = f"{COUNT_COLOR}{count}{RESET}"
                avg = f"{PRICE_COLOR}{avg}{RESET}"
                total = f"{PRICE_COLOR}{total}{RESET}"
                growth = f"{growth_color}{growth}{RESET}"
            print(
                column_sep.join(
                    [name, count, avg, total, growth]
                )
            )
        print()

    def complete_ls(self, text, line, begidx, endidx):
        return _complete(
            text, line, [[s.name for s in Stock]]
        )

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

    # ---------------- personal rules ----------------

    def do_rules(self, arg):
        """
        rules
            show all personal rules
        rules add <rule>
            add a rule,
            e.g. 'rules add never buy on a gap up'
        rules delete <id>
            delete the rule with the given Id,
            the remaining rules are renumbered
        """
        args = arg.split(maxsplit=1)
        if not args:
            self._rules_show()
            return

        sub = args[0].lower()
        rest = args[1].strip() if len(args) > 1 else ""
        if sub == "add":
            if not rest:
                _print_wrapped("usage: rules add <rule>")
                return
            rule_id = rules_add(rest)
            _print_wrapped(f"added rule {rule_id}")
        elif sub == "delete":
            if not rest.isdigit():
                _print_wrapped("usage: rules delete <id>")
                return
            deleted = rules_delete(int(rest))
            if deleted is None:
                _print_error(
                    f"error: no rule with Id {rest}"
                )
            else:
                _print_wrapped(
                    f"deleted rule {rest}: {deleted}"
                )
        else:
            _print_error(
                f"unknown subcommand '{sub}', expected "
                "add/delete"
            )

    def _rules_show(self):
        rules = rules_get_all()
        if not rules:
            _print_wrapped(
                "no rules yet, add one with 'rules add "
                "<rule>'"
            )
            return

        color = _supports_color()
        column_sep = _column_sep(color)
        header_cols = [f"{'Id':>4}", "Rule"]
        if color:
            header_cols = [
                f"{DIM}{col}{RESET}" for col in header_cols
            ]
        separator = "-" * WIDTH
        # long rules wrap inside the Rule column so the
        # table stays WIDTH wide
        rule_width = WIDTH - 4 - 3
        print()
        print(column_sep.join(header_cols))
        print(
            f"{DIM}{separator}{RESET}"
            if color
            else separator
        )
        for rule in rules:
            lines = textwrap.wrap(
                rule["Rule"],
                rule_width,
                break_on_hyphens=False,
            ) or [""]
            for i, line in enumerate(lines):
                rule_id = (
                    f"{rule['Id']:>4}"
                    if i == 0
                    else " " * 4
                )
                if color:
                    rule_id = f"{DIM}{rule_id}{RESET}"
                    line = f"{RULE_COLOR}{line}{RESET}"
                print(column_sep.join([rule_id, line]))
        print()

    def complete_rules(self, text, line, begidx, endidx):
        return _complete(text, line, [["add", "delete"]])

    # ---------------- strategy ----------------

    def do_strategy(self, arg):
        """
        strategy [run/stop/list/get]
            not implemented yet
        """
        args = arg.split()
        if not args:
            _print_wrapped(
                "usage: strategy [run/stop/list/get]"
            )
            return

        sub = args[0].lower()
        if sub in ("run", "stop", "list", "get"):
            _print_wrapped(
                f"strategy {sub}: not implemented yet"
            )
        else:
            _print_error(
                f"unknown subcommand '{sub}', expected "
                "run/stop/list/get"
            )

    def complete_strategy(self, text, line, begidx, endidx):
        return _complete(
            text, line, [["run", "stop", "list", "get"]]
        )

    # ---------------- shell ----------------

    def do_exit(self, arg):
        """exit the shell"""
        return True

    do_quit = do_exit
    do_q = do_exit

    def do_EOF(self, arg):
        print()
        return True

    def do_help(self, arg):
        """show commands, or details with 'help <cmd>'"""
        if arg:
            command = getattr(self, f"do_{arg}", None)
            if command and command.__doc__:
                _print_dim(
                    inspect.cleandoc(command.__doc__)
                )
            else:
                _print_error(f"no help on '{arg}'")
            return
        _print_dim(HELP)

    def precmd(self, line):
        # Windows consoles/pipes may prefix input with a
        # UTF-8 BOM
        return line.replace("﻿", "").strip()

    def emptyline(self):
        # don't repeat the last command on empty input
        pass

    def default(self, line):
        _print_error(
            f"unknown command: {line.split()[0]}. Type "
            "'help' for commands."
        )


def _column_sep(color):
    return f"{DIM} | {RESET}" if color else " | "


def _print_transactions_header(color):
    """print the column names of the transactions table and
    a separator line"""
    header_cols = [
        f"{'Id':>4}",
        f"{'Date':>8}",
        f"{'Time':>5}",
        f"{'Type':>4}",
        f"{'Count':>5}",
        f"{'Price':<7}",
    ]
    if color:
        header_cols = [
            f"{DIM}{col}{RESET}" for col in header_cols
        ]
    print(_column_sep(color).join(header_cols))
    separator = "-" * WIDTH
    print(
        f"{DIM}{separator}{RESET}" if color else separator
    )


def _print_transaction_row(t, color):
    """print one transaction as a row of the transactions
    table"""
    transaction_type = t['Type'].name
    if color:
        type_color = (
            BUY_COLOR
            if transaction_type == "BUY"
            else SELL_COLOR
        )
        transaction_type = (
            f"{type_color}{transaction_type:>4}{RESET}"
        )
        short_date = _short_date(t['Date'])
        date = f"{DATE_COLOR}{short_date:>8}{RESET}"
        time = f"{DIM}{t['Time']:>5}{RESET}"
        count = f"{COUNT_COLOR}{t['Count']:>5}{RESET}"
        price = f"{PRICE_COLOR}{t['Price']:<7.2f}{RESET}"
        index = f"{DIM}{t['Index']:>4}{RESET}"
    else:
        index = f"{t['Index']:>4}"
        transaction_type = f"{transaction_type:>4}"
        date = f"{_short_date(t['Date']):>8}"
        time = f"{t['Time']:>5}"
        count = f"{t['Count']:>5}"
        price = f"{t['Price']:<7.2f}"
    print(
        _column_sep(color).join(
            [
                index,
                date,
                time,
                transaction_type,
                count,
                price,
            ]
        )
    )


def _print_total(stock, color):
    """print the stock's total count, average buy price and
    position sum"""
    total_count, avg_price = transactions_total_get(stock)
    total_sum = total_count * avg_price
    if color:
        total_line = (
            f"{DIM}total:{RESET} "
            f"{BOLD}{TOTAL_COUNT_COLOR}"
            f"{total_count}{RESET} "
            f"{BOLD}{TOTAL_STOCK_COLOR}{stock.name}{RESET}"
            f"{DIM}, avg buy{RESET} "
            f"{BOLD}{PRICE_COLOR}{avg_price:.2f}{RESET}"
            f"{DIM}, sum{RESET} "
            f"{BOLD}{PRICE_COLOR}{total_sum:.2f}{RESET}"
        )
    else:
        total_line = (
            f"total: {total_count} {stock.name}, avg buy "
            f"{avg_price:.2f}, sum {total_sum:.2f}"
        )
    print(total_line)


def _fetch_prices():
    """{stock: current price} from the API, or {} after
    printing why the prices could not be fetched"""
    try:
        return get_latest_prices()
    except KeyError as e:
        _print_error(
            f"error: missing {e.args[0]} in .env, "
            "can't get current prices"
        )
    except Exception as e:  # network or API errors
        _print_error(
            f"error: can't get current prices: {e}"
        )
    return {}


def _held_positions():
    """(stock, count, average buy price) of every stock
    whose count is not 0"""
    positions = [
        (stock, *transactions_total_get(stock))
        for stock in Stock
    ]
    return [p for p in positions if p[1] != 0]


def _gain_color(gain):
    if gain > 0:
        return BUY_COLOR
    if gain < 0:
        return SELL_COLOR
    return DIM


XTOP_SEP = " "
# a Telegram alert is sent when a held stock's gain
# reaches this (config "gain_alert", default +100)
GAIN_ALERT = config.get("gain_alert", 100)


def _xtop_rows(prices):
    """one dict per held stock: stock, count, avg, price,
    gain (count * (price - avg)) and pct; price, gain and
    pct are None without a price"""
    rows = []
    # re-read every time: the order watcher may record
    # a transaction while xtop runs
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
    the threshold; again only after it has gone below it"""

    def __init__(self, threshold, report):
        self.threshold = threshold
        self.enabled = telegram_configured()
        # report(text) shows a result line in xtop
        self.report = report
        self.note = None
        self._above = set()

    def check(self, rows):
        for row in rows:
            name = row["stock"].name
            if row["gain"] is None:
                continue
            if row["gain"] < self.threshold:
                self._above.discard(name)
            elif name not in self._above:
                self._above.add(name)
                if self.enabled:
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
        threshold = f"{self.threshold:+g}"
        lines = [f"alerts: gain >= {threshold} -> Telegram"]
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


# order_watcher.py writes a heartbeat at least every 9
# minutes (IMAP IDLE renewal)
WATCHER_STALE_SECONDS = 15 * 60
# an order the watcher could not record stays visible in
# 'status' this long
WATCHER_ERROR_DAYS = 7


def _print_watcher_status():
    """print one line about order_watcher.py from its
    heartbeat file"""
    status = watcher_status_get()
    if not status or not status.get("updated"):
        _print_wrapped("mail watcher: not started")
        return
    try:
        updated = datetime.fromisoformat(status["updated"])
    except ValueError:
        _print_wrapped("mail watcher: unknown state")
        return

    state = status.get("state", "")
    age = (datetime.now() - updated).total_seconds()
    if state == "stopped":
        line = (
            f"mail watcher: stopped {updated:%d.%m %H:%M}"
        )
    elif age > WATCHER_STALE_SECONDS:
        line = (
            "mail watcher: not responding, last seen "
            f"{updated:%d.%m %H:%M}"
        )
    elif state in ("starting", "connected", "waiting"):
        line = (
            "mail watcher: running, checked "
            f"{updated:%H:%M}"
        )
    else:
        line = f"mail watcher: {state}, {updated:%H:%M}"
    if status.get("last_order"):
        line += f", last order {status['last_order']}"
    _print_wrapped(line)

    error = status.get("last_error") or {}
    try:
        error_time = (
            datetime.fromisoformat(error["time"])
            if error.get("time")
            else None
        )
    except ValueError:
        error_time = None
    recent_error = (
        error_time
        and (datetime.now() - error_time).days
        < WATCHER_ERROR_DAYS
    )
    if recent_error:
        _print_error(
            "mail watcher error "
            f"{error_time:%d.%m %H:%M}: "
            f"{error.get('text', '')}"
        )
    if status.get("log") and (
        recent_error
        or state.startswith("crashed")
        or age > WATCHER_STALE_SECONDS
    ):
        _print_wrapped(
            f"log: {os.path.relpath(status['log'])}"
        )


def _print_dim(text):
    print(
        f"{DIM}{text}{RESET}" if _supports_color() else text
    )


def _print_wrapped(text):
    """print plain text wrapped to WIDTH, dimmed"""
    _print_dim(_wrap(text))


def _print_error(text):
    """print an error wrapped to WIDTH, not dimmed so it
    stands out"""
    print(_wrap(text))


def _wrap(text):
    return textwrap.fill(
        text,
        WIDTH,
        subsequent_indent="  ",
        break_on_hyphens=False,
    )


def _parse_stock(name):
    try:
        return Stock[name.upper()]
    except KeyError:
        raise ValueError(
            f"unknown stock '{name}', expected one of: "
            f"{', '.join(s.name for s in Stock)}"
        )


def _short_date(value):
    """Display stored dd.mm.yyyy dates as dd.mm.yy."""
    return (
        f"{value[:6]}{value[-2:]}"
        if len(value) == 10
        else value
    )


def _parse_transaction_type(name):
    try:
        return TransactionType[name.upper()]
    except KeyError:
        raise ValueError(
            f"unknown transaction type '{name}', expected "
            "buy/sell"
        )


def _complete(text, line, options_per_position):
    """complete the argument at the current position from
    options_per_position"""
    position = len(line.split()) - (1 if text else 0) - 1
    if 0 <= position < len(options_per_position):
        return [
            o
            for o in options_per_position[position]
            if o.lower().startswith(text.lower())
        ]
    return []


if __name__ == "__main__":
    try:
        NxSigShell().cmdloop()
    except KeyboardInterrupt:
        print()

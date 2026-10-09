# interactive shell for nX-sig
#
# commands:
#   transactions, tr add <stock> <buy|sell> <count> <price>
#   transactions, tr get <stock>
#   transactions, tr del-last <stock>
#   transactions, tr del <stock> <index>   (disabled, use 'tr del-last')
#   ls <stock>                       (alias for 'tr get <stock>')
#   ls                               (totals of all stocks)
#   status                           (positions with current price and gain/loss)
#   xtop [sec]                       (live prices, updated every 5 or <sec> seconds)
#   rules [add <rule>/delete <id>]   (personal rules)
#   strategy [run/stop/list/get]     (not implemented yet)
#   help, exit, quit, q

import cmd
import inspect
import os
import queue
import sys
import textwrap
from datetime import datetime

from nx_sig_db import (
    Stock,
    TransactionType,
    transactions_add_one,
    transactions_delete,
    transactions_get_all,
    transactions_total_get,
    rules_add,
    rules_delete,
    rules_get_all,
)
from trade_engine import config, get_latest_prices, start_polling

LOGO = r"""
         __  __             _
   _ __  \ \/ /       ___  (_)  __ _
  | '_ \  \  /  ____ / __| | | / _` |
  | | | | /  \ |____|\__ \ | || (_| |
  |_| |_|/_/\_\      |___/ |_| \__, |
                               |___/
"""
SUBTITLE = "  nX-sig shell. 'help' for commands, 'q' to quit"

# all output is kept within the width of the 'tr get' table so it fits a mobile screen
WIDTH = 48

# 256-color gradient, one per logo line, top to bottom: light blue -> dark green
LOGO_COLORS = [f"\033[38;5;{c}m" for c in (117, 80, 43, 36, 29, 22)]
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
RULE_COLOR = LOGO_COLORS[-1]  # dark green, the last color of the logo gradient


def _supports_color():
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return False
    if os.name == "nt":
        os.system("")  # enables ANSI escape codes in the Windows console
    return True


def _banner():
    if not _supports_color():
        return f"{LOGO}\n{SUBTITLE}\n"
    lines = LOGO.strip("\n").split("\n")
    colored = [f"{LOGO_COLORS[min(i, len(LOGO_COLORS) - 1)]}{line}{RESET}" for i, line in enumerate(lines)]
    return "\n" + "\n".join(colored) + f"\n\n{DIM}{SUBTITLE}{RESET}\n"

HELP = """
commands:
  tr add <stock> <buy|sell> <count> <price>
      record a transaction
  tr get <stock>, ls <stock>
      show transactions and total
  ls
      show totals of all stocks held
  tr del-last <stock>
      delete the last transaction
  status
      positions with current price and gain/loss
  xtop [sec]
      live prices, updated every 5 or <sec>
      seconds
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
    # \001/\002 tell readline the escape codes are zero-width so line editing stays aligned
    prompt = f"\001{PROMPT_COLOR}\002nX-sig>\001{RESET}\002 " if _supports_color() else "nX-sig> "

    def preloop(self):
        # keep '-' inside words so 'del-last' completes as one word
        try:
            import readline
            readline.set_completer_delims(readline.get_completer_delims().replace("-", ""))
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
            _print_wrapped("usage: tr [add/get/del-last] ...")
            return

        sub, rest = args[0].lower(), args[1:]
        if sub == "add":
            self._transactions_add_one(rest)
        elif sub == "get":
            self._transaction_get(rest)
        elif sub == "del-last":
            self._transactions_delete_last(rest)
        # 'tr del <stock> <index>' is disabled in favour of 'tr del-last <stock>'
        # elif sub == "del":
        #     self._transactions_delete(rest)
        else:
            _print_error(f"unknown subcommand '{sub}', expected add/get/del-last")

    def _transactions_add_one(self, args):
        if len(args) != 4:
            _print_wrapped("usage: tr add <stock> <buy|sell> <count> <price>")
            return
        try:
            stock = _parse_stock(args[0])
            transaction_type = _parse_transaction_type(args[1])
            count = int(args[2])
            price = float(args[3])
        except ValueError as e:
            _print_error(f"error: {e}")
            return
        if count <= 0 or price <= 0:
            _print_error("error: count and price must be positive")
            return

        transactions_add_one(stock, transaction_type, count, price)
        _print_wrapped(f"added {transaction_type.name} {count} {stock.name} @ {price}")

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
            _print_error(f"error: index must be a number, got '{args[1]}'")
            return
        index = int(args[1])

        transaction = next((t for t in transactions_get_all(stock) if t["Index"] == index), None)
        if transaction is None:
            _print_error(f"error: no {stock.name} transaction with Id {index}")
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
            _print_wrapped(f"no transactions for {stock.name}")
            return
        # transactions are appended, so the last row is the latest one
        self._confirm_and_delete(stock, transactions[-1])

    def _confirm_and_delete(self, stock, transaction):
        """show a transaction, ask for confirmation and delete it"""
        index = transaction["Index"]
        color = _supports_color()
        print()
        _print_transactions_header(color)
        _print_transaction_row(transaction, color)
        print()
        try:
            answer = input(f"delete this {stock.name} transaction? [y/N] ")
        except (EOFError, KeyboardInterrupt):
            # Ctrl+D / Ctrl+C at the prompt cancels instead of leaving the shell
            answer = ""
            print()
        if answer.strip().lower() not in ("y", "yes"):
            _print_wrapped("cancelled")
            return

        transactions_delete(stock, index)
        _print_wrapped(f"deleted {stock.name} transaction {index}")

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
            _print_wrapped(f"no transactions for {stock.name}")
            return

        color = _supports_color()
        print()
        _print_transactions_header(color)
        for t in transactions:
            _print_transaction_row(t, color)
        separator = "-" * WIDTH

        print(f"{DIM}{separator}{RESET}" if color else separator)
        _print_total(stock, color)
        print()


    def complete_transactions(self, text, line, begidx, endidx):
        options = [["add", "get", "del-last"], [s.name for s in Stock]]
        # only 'add' takes a transaction type after the stock name
        args = line.split()
        if len(args) > 1 and args[1].lower() == "add":
            options.append([t.name.lower() for t in TransactionType])
        return _complete(text, line, options)

    do_tr = do_transactions
    complete_tr = complete_transactions

    def do_ls(self, arg):
        """
        ls <stock>
            alias for 'transactions get <stock>'
        ls
            show count, average buy price and
            total price of all stocks held,
            and growth % (not implemented yet, 0)
        """
        args = arg.split()
        if not args:
            self._totals_all()
            return
        self._transaction_get(args)

    def _totals_all(self):
        # only stocks that are currently held
        totals = [(stock, *transactions_total_get(stock)) for stock in Stock]
        totals = [t for t in totals if t[1] != 0]
        if not totals:
            _print_wrapped("no stocks held")
            return

        color = _supports_color()
        column_sep = _column_sep(color)
        header_cols = [f"{'Name':<5}", f"{'Count':>5}", f"{'Avg Price':>9}", f"{'Total':>8}", f"{'Growth %':>8}"]
        if color:
            header_cols = [f"{DIM}{col}{RESET}" for col in header_cols]
        separator = "-" * WIDTH
        print()
        print(column_sep.join(header_cols))
        print(f"{DIM}{separator}{RESET}" if color else separator)
        for stock, total_count, avg_price in totals:
            name = f"{stock.name:<5}"
            count = f"{total_count:>5}"
            avg = f"{avg_price:>9.2f}"
            total = f"{total_count * avg_price:>8.2f}"
            growth = f"{0.0:>8.2f}"  # TODO: implement growth % calculation
            if color:
                name = f"{BOLD}{TOTAL_STOCK_COLOR}{name}{RESET}"
                count = f"{COUNT_COLOR}{count}{RESET}"
                avg = f"{PRICE_COLOR}{avg}{RESET}"
                total = f"{PRICE_COLOR}{total}{RESET}"
                growth = f"{DIM}{growth}{RESET}"
            print(column_sep.join([name, count, avg, total, growth]))
        print()

    def complete_ls(self, text, line, begidx, endidx):
        return _complete(text, line, [[s.name for s in Stock]])

    # ---------------- status ----------------

    def do_status(self, arg):
        """
        status
            show all held positions with count,
            average buy price, current price and
            state: gain/loss in money,
            count * (price - avg price)
        """
        if arg.strip():
            _print_wrapped("usage: status")
            return

        positions = [(stock, *transactions_total_get(stock)) for stock in Stock]
        positions = [p for p in positions if p[1] != 0]
        if not positions:
            _print_wrapped("no stocks held")
            return

        try:
            prices = get_latest_prices()
        except KeyError as e:
            _print_error(f"error: missing {e.args[0]} in .env, can't get current prices")
            prices = {}
        except Exception as e:  # network or API errors
            _print_error(f"error: can't get current prices: {e}")
            prices = {}

        color = _supports_color()
        column_sep = _column_sep(color)
        header_cols = [f"{'Name':<5}", f"{'Count':>5}", f"{'Avg Price':>9}", f"{'Price':>8}", f"{'State':>9}"]
        if color:
            header_cols = [f"{DIM}{col}{RESET}" for col in header_cols]
        separator = "-" * WIDTH
        print()
        print(column_sep.join(header_cols))
        print(f"{DIM}{separator}{RESET}" if color else separator)
        for stock, total_count, avg_price in positions:
            name = f"{stock.name:<5}"
            count = f"{total_count:>5}"
            avg = f"{avg_price:>9.2f}"
            price = f"{'-':>8}"
            state = f"{'-':>9}"
            state_color = DIM
            if stock.name in prices:
                current = prices[stock.name]
                gain = total_count * current - total_count * avg_price
                price = f"{current:>8.2f}"
                state = f"{gain:>+9.2f}"
                state_color = BUY_COLOR if gain > 0 else SELL_COLOR if gain < 0 else DIM
            if color:
                name = f"{BOLD}{TOTAL_STOCK_COLOR}{name}{RESET}"
                count = f"{COUNT_COLOR}{count}{RESET}"
                avg = f"{PRICE_COLOR}{avg}{RESET}"
                price = f"{PRICE_COLOR}{price}{RESET}"
                state = f"{state_color}{state}{RESET}"
            print(column_sep.join([name, count, avg, price, state]))
        print()

    # ---------------- xtop ----------------

    def do_xtop(self, arg):
        """
        xtop [sec]
            show latest prices of the config indices
            in a table updated every 5 seconds, or
            every <sec> seconds, e.g. 'xtop 10'.
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
                _print_error(f"error: seconds must be a number >= 1, got '{args[0]}'")
                return

        # the polling thread only queues results, all drawing happens here in the main thread
        updates = queue.Queue()
        stop = start_polling(interval,
                             on_update=lambda prices: updates.put((prices, None)),
                             on_error=lambda e: updates.put((None, e)))

        color = _supports_color()
        prices, previous, error, updated = {}, {}, None, None
        drawn = 0
        if color:
            print("\033[?25l", end="")  # hide the cursor while redrawing
        try:
            print()
            drawn = _draw_xtop(_xtop_lines(prices, previous, error, updated, interval, color), drawn, color)
            while True:
                try:
                    # short timeout so Ctrl+C is handled promptly, also on Windows
                    new_prices, error = updates.get(timeout=0.2)
                except queue.Empty:
                    continue
                if new_prices is not None:
                    previous, prices = prices, new_prices
                    updated = datetime.now()
                drawn = _draw_xtop(_xtop_lines(prices, previous, error, updated, interval, color), drawn, color)
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
                _print_error(f"error: no rule with Id {rest}")
            else:
                _print_wrapped(f"deleted rule {rest}: {deleted}")
        else:
            _print_error(f"unknown subcommand '{sub}', expected add/delete")

    def _rules_show(self):
        rules = rules_get_all()
        if not rules:
            _print_wrapped("no rules yet, add one with 'rules add <rule>'")
            return

        color = _supports_color()
        column_sep = _column_sep(color)
        header_cols = [f"{'Id':>4}", "Rule"]
        if color:
            header_cols = [f"{DIM}{col}{RESET}" for col in header_cols]
        separator = "-" * WIDTH
        # long rules wrap inside the Rule column so the table stays WIDTH wide
        rule_width = WIDTH - 4 - 3
        print()
        print(column_sep.join(header_cols))
        print(f"{DIM}{separator}{RESET}" if color else separator)
        for rule in rules:
            lines = textwrap.wrap(rule["Rule"], rule_width, break_on_hyphens=False) or [""]
            for i, line in enumerate(lines):
                rule_id = f"{rule['Id']:>4}" if i == 0 else " " * 4
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
            _print_wrapped("usage: strategy [run/stop/list/get]")
            return

        sub = args[0].lower()
        if sub in ("run", "stop", "list", "get"):
            _print_wrapped(f"strategy {sub}: not implemented yet")
        else:
            _print_error(f"unknown subcommand '{sub}', expected run/stop/list/get")

    def complete_strategy(self, text, line, begidx, endidx):
        return _complete(text, line, [["run", "stop", "list", "get"]])

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
                _print_dim(inspect.cleandoc(command.__doc__))
            else:
                _print_error(f"no help on '{arg}'")
            return
        _print_dim(HELP)

    def precmd(self, line):
        # Windows consoles/pipes may prefix input with a UTF-8 BOM
        return line.replace("﻿", "").strip()

    def emptyline(self):
        # don't repeat the last command on empty input
        pass

    def default(self, line):
        _print_error(f"unknown command: {line.split()[0]}. Type 'help' for commands.")


def _column_sep(color):
    return f"{DIM} | {RESET}" if color else " | "


def _print_transactions_header(color):
    """print the column names of the transactions table and a separator line"""
    header_cols = [f"{'Id':>4}", f"{'Date':>8}", f"{'Time':>5}", f"{'Type':>4}", f"{'Count':>5}", f"{'Price':<7}"]
    if color:
        header_cols = [f"{DIM}{col}{RESET}" for col in header_cols]
    print(_column_sep(color).join(header_cols))
    separator = "-" * WIDTH
    print(f"{DIM}{separator}{RESET}" if color else separator)


def _print_transaction_row(t, color):
    """print one transaction as a row of the transactions table"""
    transaction_type = t['Type'].name
    if color:
        type_color = BUY_COLOR if transaction_type == "BUY" else SELL_COLOR
        transaction_type = f"{type_color}{transaction_type:>4}{RESET}"
        date = f"{DATE_COLOR}{_short_date(t['Date']):>8}{RESET}"
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
    print(_column_sep(color).join([index, date, time, transaction_type, count, price]))


def _print_total(stock, color):
    """print the stock's total count, average buy price and position sum"""
    total_count, avg_price = transactions_total_get(stock)
    total_sum = total_count * avg_price
    if color:
        total_line = (
            f"{DIM}total:{RESET} "
            f"{BOLD}{TOTAL_COUNT_COLOR}{total_count}{RESET} "
            f"{BOLD}{TOTAL_STOCK_COLOR}{stock.name}{RESET}"
            f"{DIM}, avg buy{RESET} "
            f"{BOLD}{PRICE_COLOR}{avg_price:.2f}{RESET}"
            f"{DIM}, sum{RESET} "
            f"{BOLD}{PRICE_COLOR}{total_sum:.2f}{RESET}"
        )
    else:
        total_line = f"total: {total_count} {stock.name}, avg buy {avg_price:.2f}, sum {total_sum:.2f}"
    print(total_line)


def _xtop_lines(prices, previous, error, updated, interval, color):
    """build the lines of the 'xtop' table; change is relative to the previous update"""
    column_sep = _column_sep(color)
    header_cols = [f"{'Name':<5}", f"{'Price':>9}", f"{'Change':>8}", f"{'Chg %':>7}"]
    if color:
        header_cols = [f"{DIM}{col}{RESET}" for col in header_cols]
    separator = "-" * WIDTH
    separator = f"{DIM}{separator}{RESET}" if color else separator
    lines = [column_sep.join(header_cols), separator]

    for index in config["indices"]:
        name = f"{index:<5}"
        price = f"{'-':>9}"
        change = f"{'-':>8}"
        change_pct = f"{'-':>7}"
        change_color = DIM
        if index in prices:
            price = f"{prices[index]:>9.2f}"
            if previous.get(index):
                diff = prices[index] - previous[index]
                change = f"{diff:>+8.2f}"
                change_pct = f"{diff / previous[index] * 100:>+6.2f}%"
                change_color = BUY_COLOR if diff > 0 else SELL_COLOR if diff < 0 else DIM
        if color:
            name = f"{BOLD}{TOTAL_STOCK_COLOR}{name}{RESET}"
            price = f"{PRICE_COLOR}{price}{RESET}"
            change = f"{change_color}{change}{RESET}"
            change_pct = f"{change_color}{change_pct}{RESET}"
        lines.append(column_sep.join([name, price, change, change_pct]))

    lines.append(separator)
    if updated is None:
        status = "waiting for prices..."
    else:
        status = f"updated {updated:%H:%M:%S}, every {interval:g}s, Ctrl+C to stop"
    lines.append(f"{DIM}{status}{RESET}" if color else status)
    if error is not None:
        # keep the error on one line so the redraw line count stays stable
        lines.append(f"error: {error}"[:WIDTH])
    return lines


def _draw_xtop(lines, drawn, color):
    """draw the 'xtop' table over the previously drawn one, return the number of lines drawn"""
    if color and drawn:
        # move the cursor up to the first line of the old table and clear everything below
        sys.stdout.write(f"\033[{drawn}F\033[J")
    elif not color and drawn:
        print()
    print("\n".join(lines))
    sys.stdout.flush()
    return len(lines)


def _print_dim(text):
    print(f"{DIM}{text}{RESET}" if _supports_color() else text)


def _print_wrapped(text):
    """print plain text wrapped to WIDTH, dimmed"""
    _print_dim(_wrap(text))


def _print_error(text):
    """print an error wrapped to WIDTH, not dimmed so it stands out"""
    print(_wrap(text))


def _wrap(text):
    return textwrap.fill(text, WIDTH, subsequent_indent="  ", break_on_hyphens=False)


def _parse_stock(name):
    try:
        return Stock[name.upper()]
    except KeyError:
        raise ValueError(f"unknown stock '{name}', expected one of: "
                         f"{', '.join(s.name for s in Stock)}")


def _short_date(value):
    """Display stored dd.mm.yyyy dates as dd.mm.yy."""
    return f"{value[:6]}{value[-2:]}" if len(value) == 10 else value


def _parse_transaction_type(name):
    try:
        return TransactionType[name.upper()]
    except KeyError:
        raise ValueError(f"unknown transaction type '{name}', expected buy/sell")


def _complete(text, line, options_per_position):
    """complete the argument at the current position from options_per_position"""
    position = len(line.split()) - (1 if text else 0) - 1
    if 0 <= position < len(options_per_position):
        return [o for o in options_per_position[position] if o.lower().startswith(text.lower())]
    return []


if __name__ == "__main__":
    try:
        NxSigShell().cmdloop()
    except KeyboardInterrupt:
        print()

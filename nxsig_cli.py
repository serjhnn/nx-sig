# interactive shell for nX-sig
#
# commands:
#   transactions, tr add <stock> <buy|sell> <count> <price>
#   transactions, tr get <stock>
#   ls <stock>                       (alias for 'tr get <stock>')
#   strategy [run/stop/list/get]     (not implemented yet)
#   help, exit, quit, q

import cmd
import inspect
import os
import sys
import textwrap

from nx_sig_db import (
    Stock,
    TransactionType,
    transactions_add_one,
    transactions_get_all,
    transactions_total_get,
)

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
WIDTH = 56

# 256-color gradient, one per logo line, top to bottom: light blue -> dark green
LOGO_COLORS = [f"\033[38;5;{c}m" for c in (117, 80, 43, 36, 29, 22)]
DIM = "\033[2m"
DATE_COLOR = "\033[38;5;30m"
COUNT_COLOR = "\033[38;5;96m"
PRICE_COLOR = "\033[38;5;136m"
TOTAL_STOCK_COLOR = "\033[38;5;22m"
BUY_COLOR = "\033[38;5;28m"
SELL_COLOR = "\033[38;5;124m"
BOLD = "\033[1m"
RESET = "\033[0m"
PROMPT_COLOR = LOGO_COLORS[2]  # teal from the logo gradient


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

    # ---------------- transactions ----------------

    def do_transactions(self, arg):
        """
        tr add <stock> <buy|sell> <count> <price>
            record a transaction,
            e.g. 'tr add NVDA buy 10 120.5'
        tr get <stock>
            show all transactions and the current
            total for a stock
        tr is short for transactions
        """
        args = arg.split()
        if not args:
            _print_wrapped("usage: tr [add/get] ...")
            return

        sub, rest = args[0].lower(), args[1:]
        if sub == "add":
            self._transactions_add_one(rest)
        elif sub == "get":
            self._transaction_get(rest)
        else:
            _print_error(f"unknown subcommand '{sub}', expected add/get")

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
        column_sep = f"{DIM} | {RESET}" if color else " | "
        header_cols = [f"{'Index':>5}", f"{'Date':>10}", f"{'Time':>5}", f"{'Type':>4}", f"{'Count':>6}", f"{'Price':>10}"]
        if color:
            header_cols = [f"{DIM}{col}{RESET}" for col in header_cols]
        print()
        print(column_sep.join(header_cols))
        separator = "-" * WIDTH
        print(f"{DIM}{separator}{RESET}" if color else separator)
        for t in transactions:
            transaction_type = t['Type'].name
            if color:
                type_color = BUY_COLOR if transaction_type == "BUY" else SELL_COLOR
                transaction_type = f"{type_color}{transaction_type:>4}{RESET}"
                date = f"{DATE_COLOR}{t['Date']:>10}{RESET}"
                time = f"{DIM}{t['Time']:>5}{RESET}"
                count = f"{COUNT_COLOR}{t['Count']:>6}{RESET}"
                price = f"{PRICE_COLOR}{t['Price']:>10.2f}{RESET}"
                index = f"{DIM}{t['Index']:>5}{RESET}"
            else:
                index = f"{t['Index']:>5}"
                transaction_type = f"{transaction_type:>4}"
                date = f"{t['Date']:>10}"
                time = f"{t['Time']:>5}"
                count = f"{t['Count']:>6}"
                price = f"{t['Price']:>10.2f}"
            print(column_sep.join([index, date, time, transaction_type, count, price]))

        total_count, avg_price = transactions_total_get(stock)
        total_sum = total_count * avg_price
        print(f"{DIM}{separator}{RESET}" if color else separator)
        if color:
            total_line = (
                f"{DIM}total:{RESET} "
                f"{BOLD}{COUNT_COLOR}{total_count}{RESET} "
                f"{BOLD}{TOTAL_STOCK_COLOR}{stock.name}{RESET}"
                f"{DIM}, avg buy{RESET} "
                f"{BOLD}{PRICE_COLOR}{avg_price:.2f}{RESET}"
                f"{DIM}, sum{RESET} "
                f"{BOLD}{PRICE_COLOR}{total_sum:.2f}{RESET}"
            )
        else:
            total_line = f"total: {total_count} {stock.name}, avg buy {avg_price:.2f}, sum {total_sum:.2f}"
        print(total_line)
        print()


    def complete_transactions(self, text, line, begidx, endidx):
        return _complete(text, line, [["add", "get"], [s.name for s in Stock],
                                      [t.name.lower() for t in TransactionType]])

    do_tr = do_transactions
    complete_tr = complete_transactions

    def do_ls(self, arg):
        """
        ls <stock>
            alias for 'transactions get <stock>'
        """
        self._transaction_get(arg.split())

    def complete_ls(self, text, line, begidx, endidx):
        return _complete(text, line, [[s.name for s in Stock]])

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

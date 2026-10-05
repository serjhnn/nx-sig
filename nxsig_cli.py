# interactive shell for nX-sig
#
# commands:
#   transaction add <stock> <buy|sell> <count> <price>
#   transaction get <stock>
#   strategy [run/stop/list/get]     (not implemented yet)
#   help, exit, quit, q

import cmd
import os
import sys

from nx_sig_db import (
    Stock,
    TransactionType,
    transaction_add,
    transactions_get,
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
SUBTITLE = "  nX-sig shell. Type 'help' for commands, 'q' to quit."

# 256-color gradient, one per logo line, top to bottom: light blue -> dark green
LOGO_COLORS = [f"\033[38;5;{c}m" for c in (117, 80, 43, 36, 29, 22)]
DIM = "\033[2m"
RESET = "\033[0m"


def _banner():
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return f"{LOGO}\n{SUBTITLE}\n"

    if os.name == "nt":
        os.system("")  # enables ANSI escape codes in the Windows console
    lines = LOGO.strip("\n").split("\n")
    colored = [f"{LOGO_COLORS[min(i, len(LOGO_COLORS) - 1)]}{line}{RESET}" for i, line in enumerate(lines)]
    return "\n" + "\n".join(colored) + f"\n\n{DIM}{SUBTITLE}{RESET}\n"

HELP = """
commands:
  transaction add <stock> <buy|sell> <count> <price>   record a transaction
  transaction get <stock>                              show transactions and total
  strategy [run/stop/list/get]                         (not implemented yet)
  help [command]                                       show help
  exit, quit, q                                        leave the shell
"""


class NxSigShell(cmd.Cmd):
    intro = _banner()
    prompt = "nX-sig> "

    # ---------------- transaction ----------------

    def do_transaction(self, arg):
        """
        transaction add <stock> <buy|sell> <count> <price>
            record a transaction, e.g. 'transaction add NVDA buy 10 120.5'
        transaction get <stock>
            show all transactions and the current total for a stock
        """
        args = arg.split()
        if not args:
            print("usage: transaction [add/get] ...")
            return

        sub, rest = args[0].lower(), args[1:]
        if sub == "add":
            self._transaction_add(rest)
        elif sub == "get":
            self._transaction_get(rest)
        else:
            print(f"unknown subcommand '{sub}', expected add/get")

    def _transaction_add(self, args):
        if len(args) != 4:
            print("usage: transaction add <stock> <buy|sell> <count> <price>")
            return
        try:
            stock = _parse_stock(args[0])
            transaction_type = _parse_transaction_type(args[1])
            count = int(args[2])
            price = float(args[3])
        except ValueError as e:
            print(f"error: {e}")
            return
        if count <= 0 or price <= 0:
            print("error: count and price must be positive")
            return

        transaction_add(stock, transaction_type, count, price)
        print(f"added {transaction_type.name} {count} {stock.name} @ {price}")

    def _transaction_get(self, args):
        if len(args) != 1:
            print("usage: transaction get <stock>")
            return
        try:
            stock = _parse_stock(args[0])
        except ValueError as e:
            print(f"error: {e}")
            return

        transactions = transactions_get(stock)
        if not transactions:
            print(f"no transactions for {stock.name}")
            return

        print(f"{'Date':>10} | {'Time':>5} | {'Type':>4} | {'Count':>6} | {'Price':>10}")
        print("-" * 48)
        for t in transactions:
            print(f"{t['Date']:>10} | {t['Time']:>5} | {t['Type'].name:>4} | "
                  f"{t['Count']:>6} | {t['Price']:>10.2f}")

        total_count, total_price = transactions_total_get(stock)
        print("-" * 48)
        print(f"total: {total_count} {stock.name}, avg buy price {total_price:.2f}")

    def complete_transaction(self, text, line, begidx, endidx):
        return _complete(text, line, [["add", "get"], [s.name for s in Stock],
                                      [t.name.lower() for t in TransactionType]])

    # ---------------- strategy ----------------

    def do_strategy(self, arg):
        """
        strategy [run/stop/list/get]   (not implemented yet)
        """
        args = arg.split()
        if not args:
            print("usage: strategy [run/stop/list/get]")
            return

        sub = args[0].lower()
        if sub in ("run", "stop", "list", "get"):
            print(f"strategy {sub}: not implemented yet")
        else:
            print(f"unknown subcommand '{sub}', expected run/stop/list/get")

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
        """show available commands, or details with 'help <command>'"""
        if arg:
            return super().do_help(arg)
        print(HELP)

    def precmd(self, line):
        # Windows consoles/pipes may prefix input with a UTF-8 BOM
        return line.replace("﻿", "").strip()

    def emptyline(self):
        # don't repeat the last command on empty input
        pass

    def default(self, line):
        print(f"unknown command: {line.split()[0]}. Type 'help' for commands.")


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

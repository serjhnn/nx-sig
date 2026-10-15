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
#   bb add <stock> price <price> count <count>
#   bb ls, bb rm <stock>
#                   base buys: your last buying price
#                   of a stock, with the current price
#   background tasks, each its own process:
#   run ladder <stock> <down|up> <step> <price>
#                     save and start a new ladder
#                     (price-step alerts, ladder.py)
#   run ladder <id>   start a saved ladder again
#   stop ladder <id>  stop it
#   rm ladder <id>    delete a saved ladder
#   ls ladder         saved ladders
#   run mail-broker   start the mail watcher (./mtsig)
#   stop mail-broker  stop it
#   ps                running background tasks
#   strategy [run/stop/list/get]
#                   not implemented yet
#   help, exit, quit, q
#
# the commands live in scripts/shell/, one module per
# feature; this file puts them together into the shell

import cmd
import inspect

from storage import Stock
from shell.ui import (
    LOGO_COLORS,
    DIM,
    PROMPT_COLOR,
    RESET,
    _complete,
    _print_dim,
    _print_error,
    _print_wrapped,
    _supports_color,
)
from shell.base_trade_cmd import BaseTradeCmd
from shell.ladder_cmd import LadderCmd
from shell.mail_cmd import _mtsig
from shell.overview_cmd import OverviewCmd
from shell.rule_cmd import RuleCmd
from shell.stocks_cmd import StocksCmd
from shell.trade_cmd import TradeCmd

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
  bb add <stock> price <price> count <count>
      save a base buy (bb): a last buying price
  bb ls
      base buys with the current price
  bb rm <stock>
      delete a stock's base buy
  run ladder <stock> <down|up> <step> <price>
      price-step alerts in the background
  run ladder <id>, run mail-broker
      start a saved ladder / the mail watcher
  ps
      background tasks that are running
  ls ladder
      saved ladders with their ids
  stop ladder <id>, stop mail-broker
      stop a background task
  rm ladder <id>
      delete a saved ladder
  strategy [run/stop/list/get]
      not implemented yet
  help [command]
      show help
  exit, quit, q
      leave the shell

  tr is short for transactions
"""


class NxSigShell(
    TradeCmd,
    StocksCmd,
    OverviewCmd,
    RuleCmd,
    BaseTradeCmd,
    LadderCmd,
    cmd.Cmd,
):
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

    # ---------------- ls ----------------

    def do_ls(self, arg):
        """
        ls <stock>
            alias for 'transactions get <stock>'
        ls
            show count, average buy price and
            total price of all stocks held, and
            growth %: how much the current price
            is above (or below) the average price
        ls ladder
            the saved ladders with their ids, the
            next level they alert at and whether
            they run, see 'help run'
        """
        args = arg.split()
        if not args:
            self._totals_all()
            return
        if args[0].lower() == "ladder":
            if len(args) != 1:
                _print_wrapped("usage: ls ladder")
                return
            self._ladders_list()
            return
        self._transaction_get(args)

    def complete_ls(self, text, line, begidx, endidx):
        return _complete(
            text,
            line,
            [["ladder"] + [s.name for s in Stock]],
        )

    # ---------------- background tasks ----------------
    # every task runs as its own process, so it keeps
    # running when the shell is closed; ladders are in
    # ladder.py

    def do_run(self, arg):
        """
        run ladder <stock> <down|up> <step> <price>
            save a new ladder and start it as a
            background process: it sends a Telegram
            message each time the stock's price
            moves another <step> down (or up) from
            <price>, e.g. 'run ladder SOXL down 10
            100' at 90, 80, 70, ...
        run ladder <id>
            start saved ladder <id> again, e.g.
            after a restart, see 'ls ladder'
        run mail-broker
            start the mail watcher (./mtsig start)
            that records broker order emails, it
            keeps running when the shell is closed
        """
        args = arg.split()
        if not args:
            _print_wrapped(
                "usage: run ladder <stock> <down|up> "
                "<step> <price>, run ladder <id>, "
                "run mail-broker"
            )
            return
        task, rest = args[0].lower(), args[1:]
        if task == "ladder":
            self._run_ladder(rest)
        elif task == "mail-broker":
            if rest:
                _print_wrapped("usage: run mail-broker")
                return
            _mtsig("start")
        else:
            _print_error(
                f"unknown task '{args[0]}', expected "
                "ladder/mail-broker"
            )

    def complete_run(self, text, line, begidx, endidx):
        options = [["ladder", "mail-broker"]]
        # only a new ladder takes a stock and a direction
        args = line.split()
        if len(args) > 1 and args[1].lower() == "ladder":
            options += [
                [s.name for s in Stock],
                ["down", "up"],
            ]
        return _complete(text, line, options)

    def do_stop(self, arg):
        """
        stop ladder <id>
            stop the process of running ladder <id>,
            it stays saved, see 'ls ladder'
        stop mail-broker
            stop the mail watcher (./mtsig stop)
        """
        args = arg.split()
        usage = "usage: stop ladder <id>, stop mail-broker"
        if not args:
            _print_wrapped(usage)
            return
        task, rest = args[0].lower(), args[1:]
        if task == "ladder":
            self._stop_ladder(rest)
        elif task == "mail-broker":
            if rest:
                _print_wrapped("usage: stop mail-broker")
                return
            _mtsig("stop")
        else:
            _print_error(
                f"unknown task '{args[0]}', expected "
                "ladder/mail-broker"
            )

    def complete_stop(self, text, line, begidx, endidx):
        options = [["ladder", "mail-broker"]]
        args = line.split()
        if len(args) > 1 and args[1].lower() == "ladder":
            # the ids of the running ladders
            options.append(self._ladder_ids(running=True))
        return _complete(text, line, options)

    def do_rm(self, arg):
        """
        rm ladder <id>
            delete saved ladder <id> after
            confirmation; a running ladder is
            stopped first
        """
        self._rm_ladder(arg)

    def complete_rm(self, text, line, begidx, endidx):
        return _complete(
            text,
            line,
            [["ladder"], self._ladder_ids()],
        )

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


if __name__ == "__main__":
    try:
        NxSigShell().cmdloop()
    except KeyboardInterrupt:
        print()

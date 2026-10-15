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
# the commands live in scripts/shell/: every *_cmd.py
# has a Commands class (shell/interface.py) for one kind
# of data, collected here at start into
# NxSigShell.objects; the commands as typed now are in
# shell/old_commands.py

import cmd
import glob
import importlib
import inspect
import os

import shell
from shell.interface import Commands
from shell.old_commands import OldCommands
from shell.overview_cmd import OverviewCmd
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


def collect_commands():
    """the Commands subclasses of every
    scripts/shell/*_cmd.py, in their order"""
    folder = os.path.dirname(shell.__file__)
    found = []
    for path in sorted(
        glob.glob(os.path.join(folder, "*_cmd.py"))
    ):
        name = os.path.basename(path)[: -len(".py")]
        module = importlib.import_module(f"shell.{name}")
        found += [
            value
            for value in vars(module).values()
            if isinstance(value, type)
            and issubclass(value, Commands)
            and value.__module__ == module.__name__
        ]
    return sorted(found, key=lambda c: c.order)


class NxSigShell(OldCommands, OverviewCmd, cmd.Cmd):
    intro = _banner()
    # \001/\002 tell readline the escape codes are
    # zero-width so line editing stays aligned
    prompt = (
        f"\001{PROMPT_COLOR}\002nX-sig>\001{RESET}\002 "
        if _supports_color()
        else "nX-sig> "
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # object name -> its module, e.g. "ladder"
        self.objects = {
            c.name: c(self) for c in collect_commands()
        }
        # action -> the names of the objects that have
        # it, e.g. "rm" -> ["trade", "rule", ...]
        self.actions = {
            action: [
                name
                for name, module in self.objects.items()
                if module.supports(action)
            ]
            for action in Commands.ACTIONS
        }

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

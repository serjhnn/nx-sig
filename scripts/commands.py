# interactive shell for nX-sig, started with ./nxshell
#
# commands are <action> <object> [arguments]:
#   ls stocks              held stocks, growth %
#   ls trades [<stock>]    a stock's trades and total
#   add trade <stock> <buy|sell> count <count>
#       price <price>
#   rm trade <stock> <id>
#   ls rules, add rule <rule>, rm rule <id>
#   ls basetrades [al]     last buying prices
#   add basetrade <stock>|all
#   add basetrade <stock> price <price> count <count>
#   rm basetrade <stock>
#   ls ladders             price-step alerts
#   add ladder <stock> <down|up> <step> from <price>
#       [run]
#   run ladder <id>, stop ladder <id>, rm ladder <id>
#   run mail-broker, stop mail-broker
#   ls tasks               running background tasks
# and the commands of their own:
#   status, xtop [sec] [sip|iex] [al],
#   chart <stock> [period ...], terminal info,
#   terminal padding [<spaces>],
#   test notify <alert|ladder>,
#   strategy (not implemented yet)
#   demo <set|move|speed|reset|tour> (only in ./nxdemo)
#   help [<command>], exit, quit, q
#
# the objects live in scripts/shell/: every *_cmd.py
# has a Commands class (shell/interface.py) for one kind
# of data. this file collects them at start into
# NxSigShell.objects; the action commands (do_ls, ...)
# find the object and call its action, help and tab
# completion are built from them. see CLI_BLUEPRINT.md
#
# ./nxdemo starts the same shell as a demo, with its
# own settings and sample data (engines/demo.py), and
# the process that moves its prices
# (engines/demo_prices.py)

import cmd
import glob
import importlib
import inspect
import os
import textwrap

import config
import process
import shell
from engines import demo, demo_prices
from shell.interface import Commands
from shell.chart_cmd import ChartCmd
from shell.demo_cmd import DemoCmd, print_messages
from shell.notify_cmd import NotifyCmd
from shell.overview_cmd import OverviewCmd
from shell.terminal_cmd import TerminalCmd
from shell.ui import (
    DEFAULT_WIDTH,
    LOGO_COLORS,
    DIM,
    PROMPT_COLOR,
    RESET,
    complete_options,
    print_dim,
    print_error,
    print_wrapped,
    supports_color,
    setting_problems,
    width,
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
DEMO_SUBTITLE = (
    "  nX-sig demo: sample data, made-up prices, no\n"
    "  keys. 'help' for commands, 'q' to quit"
)


def _banner():
    """the logo and the subtitle, centered on a screen
    wider than DEFAULT_WIDTH, and the lines about
    settings that aren't used"""
    indent = " " * ((width() - DEFAULT_WIDTH) // 2)
    lines = [
        indent + line if line else line
        for line in LOGO.split("\n")
    ]
    text = DEMO_SUBTITLE if config.demo() else SUBTITLE
    subtitle = "\n".join(
        indent + line for line in text.split("\n")
    )
    problems = "".join(f"{p}\n" for p in setting_problems())
    if not supports_color():
        banner = "\n".join(lines) + f"\n{subtitle}\n"
        return banner + problems
    lines = "\n".join(lines).strip("\n").split("\n")
    last = len(LOGO_COLORS) - 1
    colored = [
        f"{LOGO_COLORS[min(i, last)]}{line}{RESET}"
        for i, line in enumerate(lines)
    ]
    banner = (
        "\n"
        + "\n".join(colored)
        + f"\n\n{DIM}{subtitle}{RESET}\n"
    )
    return banner + problems


# the commands that are not an action on an object, in
# the order of 'help'
OWN_COMMANDS = [
    "status",
    "xtop",
    "chart",
    "terminal",
    "test",
    "strategy",
    "demo",
    "help",
    "exit",
]


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


def _doc(method):
    """the help text of a command: its docstring"""
    return inspect.cleandoc(method.__doc__ or "")


def _fit(text):
    """a help text for the screen: on one wider than
    DEFAULT_WIDTH each description (the lines indented 4
    spaces) is wrapped again to fill it"""
    if width() <= DEFAULT_WIDTH:
        return text
    lines, paragraph = [], []

    def flush():
        lines.extend(
            textwrap.wrap(
                " ".join(paragraph),
                width(),
                initial_indent="    ",
                subsequent_indent="    ",
                break_on_hyphens=False,
            )
        )
        paragraph.clear()

    for line in text.split("\n"):
        if line.startswith("    "):
            paragraph.append(line.strip())
            continue
        flush()
        lines.append(line)
    flush()
    return "\n".join(lines)


def _usage(method):
    """the usage lines of a help text, the lines before
    the indented description"""
    lines = []
    for line in _doc(method).split("\n"):
        if line.startswith("    "):
            break
        lines.append(line)
    return lines


class NxSigShell(
    OverviewCmd,
    ChartCmd,
    TerminalCmd,
    NotifyCmd,
    DemoCmd,
    cmd.Cmd,
):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # at start, for the width then
        self.intro = _banner()
        self.set_prompt()
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

    def set_prompt(self):
        """the prompt in the theme now"""
        name = (
            "nX-sig demo>" if config.demo() else "nX-sig>"
        )
        # \001/\002 tell readline the escape codes are
        # zero-width so line editing stays aligned
        self.prompt = (
            f"\001{PROMPT_COLOR}\002{name}\001{RESET}\002 "
            if supports_color()
            else f"{name} "
        )

    def preloop(self):
        # keep '-' inside words so 'mail-broker' completes
        # as one word
        try:
            import readline

            readline.set_completer_delims(
                readline.get_completer_delims().replace(
                    "-", ""
                )
            )
        except ImportError:
            pass

    # ---------------- the actions ----------------

    def do_ls(self, arg):
        """list or show: ls <objects>"""
        self._action("ls", arg)

    def do_add(self, arg):
        """save a new record: add <object> ..."""
        self._action("add", arg)

    def do_rm(self, arg):
        """delete after confirmation: rm <object> ..."""
        self._action("rm", arg)

    def do_run(self, arg):
        """start a background task: run <object> ..."""
        self._action("run", arg)

    def do_stop(self, arg):
        """stop a background task: stop <object> ..."""
        self._action("stop", arg)

    def complete_ls(self, text, line, begidx, endidx):
        return self._complete_action("ls", text, line)

    def complete_add(self, text, line, begidx, endidx):
        return self._complete_action("add", text, line)

    def complete_rm(self, text, line, begidx, endidx):
        return self._complete_action("rm", text, line)

    def complete_run(self, text, line, begidx, endidx):
        return self._complete_action("run", text, line)

    def complete_stop(self, text, line, begidx, endidx):
        return self._complete_action("stop", text, line)

    def _action(self, action, arg):
        """find the object named first in arg and call
        its action with the rest of the line"""
        words = arg.split(maxsplit=1)
        expected = self._object_words(action)
        if not words:
            print_wrapped(
                f"{action}: {', '.join(expected)}"
            )
            return
        rest = words[1] if len(words) > 1 else ""
        module = self._find_object(words[0])
        if module is None:
            print_error(
                f"unknown object '{words[0]}' for "
                f"{action}, "
                f"expected {'/'.join(expected)}"
            )
            return
        if not module.supports(action):
            print_error(
                f"{module.name} has no {action}, it has "
                f"{'/'.join(module.actions())}"
            )
            return
        # plural after ls (and the module's
        # plural_actions), singular everywhere else
        right = self._object_word(module, action)
        if words[0].lower() != right:
            print_error(
                "use '"
                + " ".join([action, right, rest]).strip()
                + "'"
            )
            return
        getattr(module, action)(rest)

    def _object_word(self, module, action):
        return (
            module.plural
            if action in module.plural_actions
            else module.name
        )

    def _object_words(self, action):
        """the object words that go with action"""
        return [
            self._object_word(self.objects[name], action)
            for name in self.actions[action]
        ]

    def _find_object(self, word):
        """the module named word, in the singular or the
        plural, or None"""
        word = word.lower()
        for module in self.objects.values():
            if word in (module.name, module.plural):
                return module
        return None

    def _complete_action(self, action, text, line):
        args = line.split()
        options = [self._object_words(action)]
        module = (
            self._find_object(args[1])
            if len(args) > 1
            else None
        )
        if module and module.supports(action):
            options += module.complete(action, args[2:])
        return complete_options(text, line, options)

    # ---------------- strategy ----------------

    def do_strategy(self, arg):
        """
        strategy [run/stop/list/get]
            not implemented yet
        """
        args = arg.split()
        if not args:
            print_wrapped(
                "usage: strategy [run/stop/list/get]"
            )
            return

        sub = args[0].lower()
        if sub in ("run", "stop", "list", "get"):
            print_wrapped(
                f"strategy {sub}: not implemented yet"
            )
        else:
            print_error(
                f"unknown subcommand '{sub}', expected "
                "run/stop/list/get"
            )

    def complete_strategy(self, text, line, begidx, endidx):
        return complete_options(
            text, line, [["run", "stop", "list", "get"]]
        )

    # ---------------- shell ----------------

    def do_exit(self, arg):
        """
        exit, quit, q
            leave the shell
        """
        return True

    do_quit = do_exit
    do_q = do_exit

    def do_EOF(self, arg):
        print()
        return True

    def do_help(self, arg):
        """
        help [<command>]
            all commands, or the details of one,
            e.g. 'help add trade', 'help rm' or
            'help ladder'
        """
        words = arg.lower().split()
        if not words:
            self._help_overview()
            return
        texts = self._help_texts(words)
        if not texts:
            print_error(f"no help on '{' '.join(words)}'")
            return
        print_dim("\n".join(_fit(t) for t in texts))

    def _help_texts(self, words):
        """the help texts for 'help <words>': an action,
        an action and its object, an object, or a
        command of its own"""
        topic = words[0]
        if topic in Commands.ACTIONS:
            modules = [
                self.objects[name]
                for name in self.actions[topic]
            ]
            if len(words) > 1:
                module = self._find_object(words[1])
                modules = [
                    m for m in modules if m is module
                ]
            return [
                _doc(getattr(m, topic)) for m in modules
            ]
        if len(words) > 1:
            return []
        module = self._find_object(topic)
        if module:
            return [
                _doc(getattr(module, action))
                for action in module.actions()
            ]
        command = getattr(self, f"do_{topic}", None)
        if command and command.__doc__:
            return [_doc(command)]
        return []

    def _help_overview(self):
        lines = [
            "",
            "commands ('help <command>' for more):",
        ]
        for action in Commands.ACTIONS:
            lines.append("")
            for name in self.actions[action]:
                method = getattr(self.objects[name], action)
                lines += ["  " + l for l in _usage(method)]
        lines.append("")
        for name in OWN_COMMANDS:
            method = getattr(self, f"do_{name}")
            lines += ["  " + l for l in _usage(method)]
        lines += [
            "",
            "'help <object>' shows all its commands,",
            "e.g. 'help ladder'",
            "",
        ]
        print_dim("\n".join(lines))

    def complete_help(self, text, line, begidx, endidx):
        args = line.split()
        words = list(Commands.ACTIONS)
        for module in self.objects.values():
            words += [module.name]
            if module.plural not in ("", module.name):
                words.append(module.plural)
        options = [words + OWN_COMMANDS]
        if (
            len(args) > 1
            and args[1].lower() in Commands.ACTIONS
        ):
            options.append(
                self._object_words(args[1].lower())
            )
        return complete_options(text, line, options)

    def postcmd(self, stop, line):
        # the demo's ladder and alert messages
        if not stop:
            print_messages()
        return stop

    def precmd(self, line):
        # Windows consoles/pipes may prefix input with a
        # UTF-8 BOM
        return line.replace("﻿", "").strip()

    def emptyline(self):
        # don't repeat the last command on empty input
        pass

    def default(self, line):
        print_error(
            f"unknown command: {line.split()[0]}. Type "
            "'help' for commands."
        )


def _demo_start():
    """the demo's sample data and moving prices"""
    demo.prepare()
    try:
        demo_prices.start(os.getpid())
    except demo_prices.DemoPricesError as e:
        print_error(f"the prices don't move: {e}")


def _demo_end():
    # a running ladder or alert keeps them moving
    if not process.tasks_run():
        demo_prices.stop()


if __name__ == "__main__":
    if config.demo():
        _demo_start()
    try:
        NxSigShell().cmdloop()
    except KeyboardInterrupt:
        print()
    finally:
        if config.demo():
            _demo_end()

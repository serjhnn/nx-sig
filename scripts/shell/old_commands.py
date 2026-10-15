# old_commands: the shell's commands as they are typed
# now, until step 4 of CLI_BLUEPRINT.md replaces them
# with the verb commands (ls, add, rm, run, stop)
#
#   tr, rules, bb, ls, run, stop, rm
#
# each command finds its module in self.objects (the
# Commands collected by commands.py) and calls its
# action; the docstrings are the 'help <command>' texts.
# OldCommands is mixed into NxSigShell

from storage import Stock
from shell.ui import (
    _complete,
    _print_error,
    _print_wrapped,
)

# the tr subcommands and the trade actions they call
TR_ACTIONS = {"add": "add", "get": "ls", "del-last": "rm"}
# the tasks of run and stop
TASKS = ("ladder", "mail-broker")


def _split(arg):
    """the first word, lowercase, and the rest of the
    line"""
    words = arg.split(maxsplit=1)
    if not words:
        return "", ""
    return words[0].lower(), (
        words[1] if len(words) > 1 else ""
    )


class OldCommands:
    # ---------------- transactions ----------------

    def do_transactions(self, arg):
        """
        tr add <stock> <buy|sell> <count> <price>
            record a transaction,
            e.g. 'tr add SOXL buy 10 20.5'
        tr get <stock>
            show all transactions and the current
            total for a stock
        tr del-last <stock>
            show the last transaction of a stock
            and delete it after confirmation,
            e.g. 'tr del-last SOXL'
        tr is short for transactions
        """
        sub, rest = _split(arg)
        if not sub:
            _print_wrapped(
                "usage: tr [add/get/del-last] ..."
            )
            return
        # 'tr del <stock> <index>' is disabled in favour of
        # 'tr del-last <stock>'
        if sub not in TR_ACTIONS:
            _print_error(
                f"unknown subcommand '{sub}', expected "
                "add/get/del-last"
            )
            return
        trade = self.objects["trade"]
        getattr(trade, TR_ACTIONS[sub])(rest)

    def complete_transactions(
        self, text, line, begidx, endidx
    ):
        args = line.split()
        sub = args[1].lower() if len(args) > 1 else ""
        options = [list(TR_ACTIONS)]
        options += self.objects["trade"].complete(
            TR_ACTIONS.get(sub, "ls"), args[2:]
        )
        return _complete(text, line, options)

    do_tr = do_transactions
    complete_tr = complete_transactions

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
        sub, rest = _split(arg)
        rules = self.objects["rule"]
        if not sub:
            rules.ls("")
        elif sub == "add":
            rules.add(rest)
        elif sub == "delete":
            rules.rm(rest)
        else:
            _print_error(
                f"unknown subcommand '{sub}', expected "
                "add/delete"
            )

    def complete_rules(self, text, line, begidx, endidx):
        return _complete(text, line, [["add", "delete"]])

    # ---------------- base buy ----------------

    def do_bb(self, arg):
        """
        bb add <stock> price <price> count <count>
            save the base buy of <stock>: the last
            price you bought it at and how many,
            e.g. 'bb add MRVU price 100 count 10';
            replaces the stock's older base buy
        bb ls
            the base buys in config order, with
            the current price of each stock and its
            change % from the buying price
        bb rm <stock>
            delete the base buy of <stock>, after
            confirmation
        bb is short for base buy
        """
        args = arg.split()
        if not args:
            self.do_help("bb")
            return
        action, rest = _split(arg)
        if action not in ("add", "ls", "rm"):
            _print_error(
                f"unknown action '{args[0]}' for bb, "
                "expected add/ls/rm"
            )
            return
        getattr(self.objects["basetrade"], action)(rest)

    def complete_bb(self, text, line, begidx, endidx):
        args = line.split()
        action = args[1].lower() if len(args) > 1 else ""
        options = [["add", "ls", "rm"]]
        if action in options[0]:
            options += self.objects["basetrade"].complete(
                action, args[2:]
            )
        return _complete(text, line, options)

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
        word, rest = _split(arg)
        if not word:
            self.objects["stocks"].ls("")
        elif word == "ladder":
            self.objects["ladder"].ls(rest)
        else:
            self.objects["trade"].ls(arg)

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
        task, rest = _split(arg)
        if not task:
            _print_wrapped(
                "usage: run ladder <stock> <down|up> "
                "<step> <price>, run ladder <id>, "
                "run mail-broker"
            )
            return
        self._task_action("run", arg, rest)

    def complete_run(self, text, line, begidx, endidx):
        return self._complete_task("run", text, line)

    def do_stop(self, arg):
        """
        stop ladder <id>
            stop the process of running ladder <id>,
            it stays saved, see 'ls ladder'
        stop mail-broker
            stop the mail watcher (./mtsig stop)
        """
        task, rest = _split(arg)
        if not task:
            _print_wrapped(
                "usage: stop ladder <id>, stop mail-broker"
            )
            return
        self._task_action("stop", arg, rest)

    def complete_stop(self, text, line, begidx, endidx):
        return self._complete_task("stop", text, line)

    def do_rm(self, arg):
        """
        rm ladder <id>
            delete saved ladder <id> after
            confirmation; a running ladder is
            stopped first
        """
        args = arg.split()
        if len(args) != 2 or args[0].lower() != "ladder":
            _print_wrapped("usage: rm ladder <id>")
            return
        self.objects["ladder"].rm(args[1])

    def complete_rm(self, text, line, begidx, endidx):
        args = line.split()
        options = [["ladder"]]
        options += self.objects["ladder"].complete(
            "rm", args[2:]
        )
        return _complete(text, line, options)

    def _task_action(self, action, arg, rest):
        """call run or stop of the task named first in
        arg"""
        task = arg.split()[0]
        if task.lower() not in TASKS:
            _print_error(
                f"unknown task '{task}', expected "
                "ladder/mail-broker"
            )
            return
        getattr(self.objects[task.lower()], action)(rest)

    def _complete_task(self, action, text, line):
        args = line.split()
        task = args[1].lower() if len(args) > 1 else ""
        options = [list(TASKS)]
        if task in TASKS:
            options += self.objects[task].complete(
                action, args[2:]
            )
        return _complete(text, line, options)

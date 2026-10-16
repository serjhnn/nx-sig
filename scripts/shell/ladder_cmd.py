# ladder_cmd: the shell side of the ladders, the engine
# is scripts/ladder.py
#
#   add ladder <stock> <down|up> <step> from <price>
#       [run]
#   run ladder <id> [force], stop ladder <id>,
#   rm ladder <id>
#   ls ladders
#
# LadderCommands implements them for the verb commands
# of commands.py; its tasks() are the ladders' rows in
# 'ls tasks'

from datetime import datetime

import ladder
import tasks_owner
from storage import (
    Stock,
    ladder_get,
    ladder_status_get,
    ladders_get_all,
)
from telegram_notify import (
    is_configured as telegram_configured,
)
from shell.interface import Commands
from shell.ui import (
    BOLD,
    BUY_COLOR,
    DIM,
    PRICE_COLOR,
    RESET,
    SELL_COLOR,
    TOTAL_STOCK_COLOR,
    WIDTH,
    _confirm,
    _parse_direction,
    _parse_id,
    _parse_stock,
    _print_error,
    _print_wrapped,
    _supports_color,
)

ADD_USAGE = (
    "usage: add ladder <stock> <down|up> <step> from "
    "<price> [run]"
)


class LadderCommands(Commands):
    name = "ladder"
    plural = "ladders"
    order = 30

    def ls(self, arg):
        """
        ls ladders
            the saved ladders with their ids, the
            next level they alert at and whether
            they run
        """
        if arg.split():
            _print_wrapped("usage: ls ladders")
            return
        ladders = ladders_get_all()
        if not ladders:
            _print_wrapped(
                "no ladders yet, see 'help add ladder'"
            )
            return
        _print_ladders(ladders)

    def add(self, arg):
        """
        add ladder <stock> <down|up> <step>
          from <price> [run]
            save a ladder: a Telegram message each
            time the price moves another <step>
            down (or up) from <price>, e.g. 'add
            ladder SOXL down 10 from 100' at 90,
            80, 70, ...; run starts it right away
        """
        args = arg.split()
        start = len(args) == 6 and args[5].lower() == "run"
        if len(args) not in (5, 6) or (
            len(args) == 6 and not start
        ):
            _print_wrapped(ADD_USAGE)
            return
        if args[3].lower() != "from":
            _print_wrapped(ADD_USAGE)
            return
        ladder_id = self._save(args[:3] + args[4:5])
        if ladder_id is None:
            return
        if start:
            self._start_ladder(ladder_id)
        else:
            _print_wrapped(
                f"start it with 'run ladder {ladder_id}'"
            )

    def run(self, arg):
        """
        run ladder <id> [force]
            start a saved ladder as a background
            process, it keeps running when the
            shell is closed; only one device runs
            the background tasks, force takes them
            over from the other one (when it is off)
        """
        args = arg.split()
        force = len(args) == 2 and (
            args[1].lower() == "force"
        )
        ladder_id = (
            _parse_id(args[0])
            if len(args) == 1 or force
            else None
        )
        if ladder_id is None:
            _print_wrapped("usage: run ladder <id> [force]")
            return
        self._start_ladder(ladder_id, force)

    def stop(self, arg):
        """
        stop ladder <id>
            stop a running ladder, it stays saved
        """
        args = arg.split()
        ladder_id = (
            _parse_id(args[0]) if len(args) == 1 else None
        )
        if ladder_id is None:
            _print_wrapped("usage: stop ladder <id>")
            return
        try:
            stopped = ladder.stop(ladder_id)
        except ladder.LadderError as e:
            _print_error(f"error: {e}")
            return
        _print_wrapped(
            f"ladder {ladder_id} stopped"
            if stopped
            else f"ladder {ladder_id} is not running"
        )

    def rm(self, arg):
        """
        rm ladder <id>
            delete a saved ladder after
            confirmation; a running ladder is
            stopped first
        """
        args = arg.split()
        ladder_id = (
            _parse_id(args[0]) if len(args) == 1 else None
        )
        if ladder_id is None:
            _print_wrapped("usage: rm ladder <id>")
            return
        saved = ladder_get(ladder_id)
        if saved is None:
            _print_error(
                f"error: no ladder {ladder_id}, "
                "see 'ls ladders'"
            )
            return
        _print_ladders([saved])
        running = ladder.running_pid(ladder_id)
        question = (
            f"stop and delete ladder {ladder_id}? [y/N] "
            if running
            else f"delete ladder {ladder_id}? [y/N] "
        )
        if not _confirm(question):
            _print_wrapped("cancelled")
            return
        try:
            was_running = ladder.remove(ladder_id)
        except (ladder.LadderError, OSError) as e:
            _print_error(f"error: {e}")
            return
        _print_wrapped(
            f"ladder {ladder_id} "
            + ("stopped and " if was_running else "")
            + "deleted"
        )

    def complete(self, action, args):
        if action == "add":
            return [
                [s.name for s in Stock],
                ["down", "up"],
                [],
                ["from"],
                [],
                ["run"],
            ]
        if action == "run":
            # the ids of the ladders that don't run
            return [
                self._ladder_ids(running=False),
                ["force"],
            ]
        if action == "stop":
            # the ids of the running ladders
            return [self._ladder_ids(running=True)]
        if action == "rm":
            return [self._ladder_ids()]
        return []

    def tasks(self):
        tasks = [_ladder_task(l) for l in ladders_get_all()]
        return [t for t in tasks if t]

    def _save(self, args):
        """check and save a new ladder from its stock,
        direction, step and price, return its Id or
        None"""
        try:
            stock = _parse_stock(args[0])
            direction = _parse_direction(args[1])
        except ValueError as e:
            _print_error(f"error: {e}")
            return None
        try:
            step = float(args[2])
            price = float(args[3])
        except ValueError:
            _print_error(
                "error: step and price must be numbers"
            )
            return None
        if not telegram_configured():
            _print_error(
                "error: Telegram isn't set up, add TOKEN "
                "and CHAT_ID to .env"
            )
            return None
        try:
            ladder_id = ladder.create(
                stock.name, direction, step, price
            )
        except ladder.LadderError as e:
            _print_error(f"error: {e}")
            return None
        _print_wrapped(
            f"ladder {ladder_id} saved: {stock.name} "
            f"{direction} every {step:g} from {price:g}"
        )
        return ladder_id

    def _start_ladder(self, ladder_id, force=False):
        if force and tasks_owner.lost():
            _print_wrapped(
                "taking over the background tasks from "
                + tasks_owner.describe(tasks_owner.owner())
            )
        _print_wrapped(f"starting ladder {ladder_id}...")
        try:
            pid = ladder.start(ladder_id, force)
        except ladder.LadderError as e:
            _print_error(f"error: {e}")
            return
        saved = ladder_get(ladder_id)
        _print_wrapped(
            f"ladder {ladder_id} started (pid {pid}), "
            f"next alert at {ladder.next_level(saved):g}"
        )

    def _ladder_ids(self, running=None):
        """the ids of the saved ladders; with running
        True or False only of the ones that run or
        don't"""
        return [
            str(l["Id"])
            for l in ladders_get_all()
            if running is None
            or bool(ladder.running_pid(l["Id"])) == running
        ]


def _ladder_task(saved):
    """the 'ls tasks' row of a ladder, or None if it
    isn't running"""
    pid = ladder.running_pid(saved["Id"])
    if not pid:
        return None
    status = ladder_status_get(saved["Id"]) or {}
    started = updated = None
    try:
        started = datetime.fromisoformat(status["started"])
        updated = datetime.fromisoformat(status["updated"])
    except (KeyError, TypeError, ValueError):
        pass
    state = status.get("state") or "-"
    healthy = state in ("starting", "waiting")
    if updated:
        age = (datetime.now() - updated).total_seconds()
        if age > ladder.STALE_SECONDS:
            state, healthy = "no reply", False
    return {
        "id": saved["Id"],
        "task": f"ladder {saved['Stock']}",
        "pid": pid,
        "started": started,
        "state": state,
        "healthy": healthy,
    }


def _print_ladders(ladders):
    """the ls ladders table: Id, Stock, Ladder
    (direction and step), From, Next (the next alert),
    State"""
    color = _supports_color()
    sep = "  "
    header = sep.join(
        [
            f"{'Id':>2}",
            f"{'Stock':<5}",
            f"{'Ladder':<9}",
            f"{'From':>7}",
            f"{'Next':>7}",
            f"{'State':<7}",
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
    for saved in ladders:
        running = ladder.running_pid(saved["Id"])
        if running:
            state = "running"
        else:
            status = ladder_status_get(saved["Id"]) or {}
            # done: a down ladder that has no levels left
            state = (
                status["state"]
                if status.get("state")
                in ("done", "crashed")
                else "stopped"
            )
        steps = f"{saved['Direction']} {saved['Step']:g}"
        next_level = (
            "-"
            if state == "done"
            else f"{ladder.next_level(saved):.2f}"
        )
        cols = [
            f"{saved['Id']:>2}",
            f"{saved['Stock']:<5.5}",
            f"{steps:<9.9}",
            f"{saved['From']:>7.2f}",
            f"{next_level:>7}",
            f"{state:<7}",
        ]
        if color:
            state_color = {
                "running": BUY_COLOR,
                "crashed": SELL_COLOR,
            }.get(state, DIM)
            cols = [
                f"{DIM}{cols[0]}{RESET}",
                f"{BOLD}{TOTAL_STOCK_COLOR}"
                f"{cols[1]}{RESET}",
                cols[2],
                f"{PRICE_COLOR}{cols[3]}{RESET}",
                f"{PRICE_COLOR}{cols[4]}{RESET}",
                f"{state_color}{cols[5]}{RESET}",
            ]
        print(sep.join(cols))
    print()

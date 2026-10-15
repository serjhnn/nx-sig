# ladder_cmd: the shell side of the ladders, the engine
# is scripts/ladder.py
#
#   run ladder <stock> <down|up> <step> <price>
#   run ladder <id>, stop ladder <id>, rm ladder <id>
#   ls ladder
#
# LadderCmd is mixed into NxSigShell; the run, stop, rm
# and ls commands in commands.py call its methods.
# _ladder_task(saved) is the ladder's row in 'ps'

from datetime import datetime

import ladder
from storage import (
    ladder_get,
    ladder_status_get,
    ladders_get_all,
)
from telegram_notify import (
    is_configured as telegram_configured,
)
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


class LadderCmd:
    def _run_ladder(self, args):
        usage = (
            "usage: run ladder <stock> <down|up> <step> "
            "<price>, or run ladder <id>"
        )
        if len(args) == 1:
            ladder_id = _parse_id(args[0])
            if ladder_id is None:
                _print_wrapped(usage)
                return
            self._start_ladder(ladder_id)
            return
        if len(args) != 4:
            _print_wrapped(usage)
            return
        try:
            stock = _parse_stock(args[0])
            direction = _parse_direction(args[1])
        except ValueError as e:
            _print_error(f"error: {e}")
            return
        try:
            step = float(args[2])
            price = float(args[3])
        except ValueError:
            _print_error(
                "error: step and price must be numbers"
            )
            return
        if not telegram_configured():
            _print_error(
                "error: Telegram isn't set up, add TOKEN "
                "and CHAT_ID to .env"
            )
            return
        try:
            ladder_id = ladder.create(
                stock.name, direction, step, price
            )
        except ladder.LadderError as e:
            _print_error(f"error: {e}")
            return
        _print_wrapped(
            f"ladder {ladder_id} saved: {stock.name} "
            f"{direction} every {step:g} from {price:g}"
        )
        self._start_ladder(ladder_id)

    def _start_ladder(self, ladder_id):
        _print_wrapped(f"starting ladder {ladder_id}...")
        try:
            pid = ladder.start(ladder_id)
        except ladder.LadderError as e:
            _print_error(f"error: {e}")
            return
        saved = ladder_get(ladder_id)
        _print_wrapped(
            f"ladder {ladder_id} started (pid {pid}), "
            f"next alert at {ladder.next_level(saved):g}"
        )

    def _stop_ladder(self, rest):
        ladder_id = (
            _parse_id(rest[0]) if len(rest) == 1 else None
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

    def _rm_ladder(self, arg):
        args = arg.split()
        ladder_id = (
            _parse_id(args[1])
            if len(args) == 2
            and args[0].lower() == "ladder"
            else None
        )
        if ladder_id is None:
            _print_wrapped("usage: rm ladder <id>")
            return
        saved = ladder_get(ladder_id)
        if saved is None:
            _print_error(
                f"error: no ladder {ladder_id}, "
                "see 'ls ladder'"
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

    def _ladders_list(self):
        ladders = ladders_get_all()
        if not ladders:
            _print_wrapped(
                "no ladders saved, see 'help run'"
            )
            return
        _print_ladders(ladders)

    def _ladder_ids(self, running=False):
        """the ids of the saved ladders, or of the
        running ones only"""
        return [
            str(l["Id"])
            for l in ladders_get_all()
            if not running or ladder.running_pid(l["Id"])
        ]


def _ladder_task(saved):
    """the ps row of a ladder, or None if it isn't
    running"""
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
    """the ls ladder table: Id, Stock, Ladder (direction
    and step), From, Next (the next alert), State"""
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

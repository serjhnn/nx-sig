# tasks_cmd: the background tasks, every one runs as its
# own process
#
#   ls tasks
#
# TaskCommands joins the tasks() rows of every module
# (the ladders, the mail broker), so a new feature with
# background tasks adds itself here

from shell.interface import Commands
from shell.ui import (
    BOLD,
    BUY_COLOR,
    COUNT_COLOR,
    DATE_COLOR,
    DIM,
    RESET,
    SELL_COLOR,
    TOTAL_STOCK_COLOR,
    WIDTH,
    _print_wrapped,
    _supports_color,
)


class TaskCommands(Commands):
    name = "task"
    plural = "tasks"
    order = 70

    def ls(self, arg):
        """
        ls tasks
            the background tasks that are running
            as their own process, with their pid,
            start time and state
        """
        if arg.split():
            _print_wrapped("usage: ls tasks")
            return
        tasks = [
            task
            for module in self.shell.objects.values()
            if module is not self
            for task in module.tasks()
        ]
        if not tasks:
            _print_wrapped("no background tasks running")
            return
        _print_tasks(tasks)


def _print_tasks(tasks):
    """the ls tasks table: Id, Task, PID, Started,
    State"""
    color = _supports_color()
    sep = "  "
    header = sep.join(
        [
            f"{'Id':>2}",
            f"{'Task':<11}",
            f"{'PID':>7}",
            f"{'Started':<11}",
            f"{'State':<9}",
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
    for t in tasks:
        started = (
            f"{t['started']:%d.%m %H:%M}"
            if t["started"]
            else "-"
        )
        cols = [
            f"{t['id']:>2}",
            f"{t['task']:<11.11}",
            f"{t['pid']:>7}",
            f"{started:<11}",
            f"{t['state']:<9.9}",
        ]
        if color:
            state_color = (
                BUY_COLOR if t["healthy"] else SELL_COLOR
            )
            cols = [
                f"{DIM}{cols[0]}{RESET}",
                f"{BOLD}{TOTAL_STOCK_COLOR}"
                f"{cols[1]}{RESET}",
                f"{COUNT_COLOR}{cols[2]}{RESET}",
                f"{DATE_COLOR}{cols[3]}{RESET}",
                f"{state_color}{cols[4]}{RESET}",
            ]
        print(sep.join(cols))
    print()

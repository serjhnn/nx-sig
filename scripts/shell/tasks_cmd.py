# tasks_cmd: the background tasks, every one runs as its
# own process
#
#   ls tasks
#   stop tasks all
#
# TaskCommands joins the tasks() rows of every module
# (the ladders, the mail broker), so a new feature with
# background tasks adds itself here. print_owner() is
# the line about the device that runs them
# (tasks_owner.py), also in 'status'

import tasks_owner
from shell.interface import Commands
from shell.ui import (
    print_table,
    rule,
    BOLD,
    BUY_COLOR,
    COUNT_COLOR,
    DATE_COLOR,
    DIM,
    RESET,
    SELL_COLOR,
    TOTAL_STOCK_COLOR,
    space_separator,
    print_wrapped,
    supports_color,
)


class TaskCommands(Commands):
    name = "task"
    plural = "tasks"
    order = 70
    plural_actions = ("ls", "stop")

    def ls(self, arg):
        """
        ls tasks
            the background tasks that are running
            as their own process, with their pid,
            start time and state, and the device
            that runs them
        """
        if arg.split():
            print_wrapped("usage: ls tasks")
            return
        tasks = [
            task
            for module in self.shell.objects.values()
            if module is not self
            for task in module.tasks()
        ]
        if not tasks:
            print_wrapped("no background tasks running")
        else:
            _print_tasks(tasks)
        print_owner()

    def stop(self, arg):
        """
        stop tasks all
            stop every background task running on
            this device: the ladders, the alerts
            and the mail broker, as their own stop
            commands do; they stay saved
        """
        if arg.lower().split() != ["all"]:
            print_wrapped("usage: stop tasks all")
            return
        stopped = False
        for module in self.shell.objects.values():
            if module is self or not module.supports(
                "stop"
            ):
                continue
            for task in module.tasks():
                # a ladder's stop takes its id, the
                # others nothing
                task_id = task["id"]
                module.stop(
                    "" if task_id == "-" else str(task_id)
                )
                stopped = True
        if not stopped:
            print_wrapped("no background tasks running")

    def complete(self, action, args):
        return [["all"]] if action == "stop" else []


def print_owner():
    """the device that runs the background tasks, if
    one does"""
    current = tasks_owner.owner()
    if current is None:
        return
    if current["id"] == tasks_owner.this_device()["id"]:
        where = f"here ({current['name']})"
    else:
        where = f"on {tasks_owner.describe(current)}"
    print_wrapped(f"background tasks run {where}")


def _print_tasks(tasks):
    """the ls tasks table: Id, Task, PID, Started,
    State"""
    color = supports_color()
    sep = space_separator(5, 2)
    header = sep.join(
        [
            f"{'Id':>2}",
            f"{'Task':<11}",
            f"{'PID':>7}",
            f"{'Started':<11}",
            f"{'State':<9}",
        ]
    )
    separator = rule(header)
    if color:
        lines = [
            f"{DIM}{header}{RESET}",
            f"{DIM}{separator}{RESET}",
        ]
    else:
        lines = [header, separator]
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
        lines.append(sep.join(cols))
    print()
    print_table(lines)
    print()

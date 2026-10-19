# rule_cmd: your personal trading rules
#
#   ls rules, add rule <rule>, rm rule <id>
#
# RuleCommands implements them for the verb commands of
# commands.py

import textwrap

from engines import rules
from shell.interface import Commands
from shell.ui import (
    DIM,
    RESET,
    RULE_COLOR,
    width,
    column_separator,
    confirm,
    parse_id,
    print_error,
    print_wrapped,
    supports_color,
)


class RuleCommands(Commands):
    name = "rule"
    plural = "rules"
    order = 30

    def ls(self, arg):
        """
        ls rules
            your personal rules with their ids
        """
        if arg.split():
            print_wrapped("usage: ls rules")
            return
        found = rules.get_all()
        if not found:
            print_wrapped(
                "no rules yet, add one with 'add rule "
                "<rule>'"
            )
            return
        _print_rules(found)

    def add(self, arg):
        """
        add rule <rule>
            save a personal rule, e.g. 'add rule
            never buy on a gap up'
        """
        rule = arg.strip()
        if not rule:
            print_wrapped("usage: add rule <rule>")
            return
        rule_id = rules.add(rule)
        print_wrapped(f"added rule {rule_id}")

    def rm(self, arg):
        """
        rm rule <id>
            delete a rule after confirmation, the
            rules after it are renumbered
        """
        args = arg.split()
        rule_id = (
            parse_id(args[0]) if len(args) == 1 else None
        )
        if rule_id is None:
            print_wrapped("usage: rm rule <id>")
            return
        rule = rules.get(rule_id)
        if rule is None:
            print_error(
                f"error: no rule {rule_id}, see 'ls rules'"
            )
            return
        _print_rules([rule])
        if not confirm(f"delete rule {rule_id}? [y/N] "):
            print_wrapped("cancelled")
            return
        rules.delete(rule_id)
        print_wrapped(f"deleted rule {rule_id}")

    def complete(self, action, args):
        if action == "rm":
            return [[str(r["Id"]) for r in rules.get_all()]]
        return []


def _print_rules(found):
    """the rules table: Id and Rule, long rules wrap
    inside the Rule column"""
    color = supports_color()
    column_sep = column_separator(color)
    header_cols = [f"{'Id':>4}", "Rule"]
    if color:
        header_cols = [
            f"{DIM}{col}{RESET}" for col in header_cols
        ]
    separator = "-" * width()
    # long rules wrap inside the Rule column so the
    # table stays width() wide
    rule_width = width() - 4 - 3
    print()
    print(column_sep.join(header_cols))
    print(
        f"{DIM}{separator}{RESET}" if color else separator
    )
    for rule in found:
        lines = textwrap.wrap(
            rule["Rule"],
            rule_width,
            break_on_hyphens=False,
        ) or [""]
        for i, line in enumerate(lines):
            rule_id = (
                f"{rule['Id']:>4}" if i == 0 else " " * 4
            )
            if color:
                rule_id = f"{DIM}{rule_id}{RESET}"
                line = f"{RULE_COLOR}{line}{RESET}"
            print(column_sep.join([rule_id, line]))
    print()

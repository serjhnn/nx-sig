# rule_cmd: your personal trading rules
#
#   ls rules, add rule <rule>, rm rule <id>
#
# RuleCommands implements them for the verb commands of
# commands.py

import textwrap

from storage import rules_add, rules_delete, rules_get_all
from shell.interface import Commands
from shell.ui import (
    DIM,
    RESET,
    RULE_COLOR,
    WIDTH,
    _column_sep,
    _confirm,
    _parse_id,
    _print_error,
    _print_wrapped,
    _supports_color,
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
            _print_wrapped("usage: ls rules")
            return
        rules = rules_get_all()
        if not rules:
            _print_wrapped(
                "no rules yet, add one with 'add rule "
                "<rule>'"
            )
            return
        _print_rules(rules)

    def add(self, arg):
        """
        add rule <rule>
            save a personal rule, e.g. 'add rule
            never buy on a gap up'
        """
        rule = arg.strip()
        if not rule:
            _print_wrapped("usage: add rule <rule>")
            return
        rule_id = rules_add(rule)
        _print_wrapped(f"added rule {rule_id}")

    def rm(self, arg):
        """
        rm rule <id>
            delete a rule after confirmation, the
            rules after it are renumbered
        """
        args = arg.split()
        rule_id = (
            _parse_id(args[0]) if len(args) == 1 else None
        )
        if rule_id is None:
            _print_wrapped("usage: rm rule <id>")
            return
        rule = next(
            (
                r
                for r in rules_get_all()
                if r["Id"] == rule_id
            ),
            None,
        )
        if rule is None:
            _print_error(
                f"error: no rule {rule_id}, see 'ls rules'"
            )
            return
        _print_rules([rule])
        if not _confirm(f"delete rule {rule_id}? [y/N] "):
            _print_wrapped("cancelled")
            return
        rules_delete(rule_id)
        _print_wrapped(f"deleted rule {rule_id}")

    def complete(self, action, args):
        if action == "rm":
            return [[str(r["Id"]) for r in rules_get_all()]]
        return []


def _print_rules(rules):
    """the rules table: Id and Rule, long rules wrap
    inside the Rule column"""
    color = _supports_color()
    column_sep = _column_sep(color)
    header_cols = [f"{'Id':>4}", "Rule"]
    if color:
        header_cols = [
            f"{DIM}{col}{RESET}" for col in header_cols
        ]
    separator = "-" * WIDTH
    # long rules wrap inside the Rule column so the
    # table stays WIDTH wide
    rule_width = WIDTH - 4 - 3
    print()
    print(column_sep.join(header_cols))
    print(
        f"{DIM}{separator}{RESET}" if color else separator
    )
    for rule in rules:
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

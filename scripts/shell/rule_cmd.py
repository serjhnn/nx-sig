# rule_cmd: the personal rules commands of the shell
#
#   rules, rules add <rule>, rules delete <id>
#
# RuleCmd is mixed into NxSigShell

import textwrap

from storage import rules_add, rules_delete, rules_get_all
from shell.ui import (
    DIM,
    RESET,
    RULE_COLOR,
    WIDTH,
    _column_sep,
    _complete,
    _print_error,
    _print_wrapped,
    _supports_color,
)


class RuleCmd:
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
        args = arg.split(maxsplit=1)
        if not args:
            self._rules_show()
            return

        sub = args[0].lower()
        rest = args[1].strip() if len(args) > 1 else ""
        if sub == "add":
            if not rest:
                _print_wrapped("usage: rules add <rule>")
                return
            rule_id = rules_add(rest)
            _print_wrapped(f"added rule {rule_id}")
        elif sub == "delete":
            if not rest.isdigit():
                _print_wrapped("usage: rules delete <id>")
                return
            deleted = rules_delete(int(rest))
            if deleted is None:
                _print_error(
                    f"error: no rule with Id {rest}"
                )
            else:
                _print_wrapped(
                    f"deleted rule {rest}: {deleted}"
                )
        else:
            _print_error(
                f"unknown subcommand '{sub}', expected "
                "add/delete"
            )

    def _rules_show(self):
        rules = rules_get_all()
        if not rules:
            _print_wrapped(
                "no rules yet, add one with 'rules add "
                "<rule>'"
            )
            return

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
            f"{DIM}{separator}{RESET}"
            if color
            else separator
        )
        for rule in rules:
            lines = textwrap.wrap(
                rule["Rule"],
                rule_width,
                break_on_hyphens=False,
            ) or [""]
            for i, line in enumerate(lines):
                rule_id = (
                    f"{rule['Id']:>4}"
                    if i == 0
                    else " " * 4
                )
                if color:
                    rule_id = f"{DIM}{rule_id}{RESET}"
                    line = f"{RULE_COLOR}{line}{RESET}"
                print(column_sep.join([rule_id, line]))
        print()

    def complete_rules(self, text, line, begidx, endidx):
        return _complete(text, line, [["add", "delete"]])

# rules: the rules engine, your personal trading rules
#
#   python tests/test_rules.py   the tests
#
# the shell's rule commands (shell/rule_cmd.py) use it;
# storage.py only reads and writes personal_rules.json.
#
# public functions:
#   add(rule)          save a rule, return its id
#   delete(rule_id)    the deleted rule's text, or None;
#                      the rules after it are renumbered
#   get(rule_id)       the rule, or None
#   get_all()          the rules, numbered from 1
#
# a rule is {"Id", "Rule"}

import storage


def add(rule):
    return storage.rules_add(rule)


def delete(rule_id):
    return storage.rules_delete(rule_id)


def get(rule_id):
    return next(
        (r for r in get_all() if r["Id"] == rule_id),
        None,
    )


def get_all():
    return storage.rules_get_all()

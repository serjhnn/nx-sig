# shell_test: tests of the nxshell commands
#
#   python scripts/shell_test.py
#
# every test runs commands through NxSigShell.onecmd()
# against a temporary data folder, so the real data is
# not touched. the prices, Telegram, the ladder
# processes and ./mtsig are faked: nothing is started
# and nothing is sent. every printed line is also
# checked to fit WIDTH.
#
# the fakes replace the engines (trade_engine, ladder,
# subprocess, the .env keys), not names inside the
# shell, so they work wherever the shell code lives.
#
# the tests pin down what the commands print now, so a
# change of the shell (see CLI_BLUEPRINT.md) shows what
# it changes.

import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from unittest import mock

# plain output without color codes
os.environ["NO_COLOR"] = "1"

import ladder
import storage
import trade_engine
from commands import NxSigShell
from shell.overview_cmd import _xtop_lines
from shell.ui import WIDTH

FAKE_PID = 4242


class ShellTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._db_dir = storage.DB_DIR
        storage.DB_DIR = self._tmp.name
        # {stock name: price}, what the fake API returns
        self.prices = {}
        # the ids of the ladders that "run"
        self.running = set()
        # what ./mtsig was called with
        self.mtsig_calls = []
        self._patches = [
            # the API keys and the request
            mock.patch.object(
                trade_engine, "_headers", lambda: {}
            ),
            mock.patch.object(
                trade_engine,
                "_latest_prices",
                lambda headers: dict(self.prices),
            ),
            # Telegram is set up, but never called
            mock.patch.dict(
                os.environ,
                {"TOKEN": "test", "CHAT_ID": "test"},
            ),
            mock.patch.object(
                ladder, "start", self._fake_start
            ),
            mock.patch.object(
                ladder, "stop", self._fake_stop
            ),
            mock.patch.object(
                ladder,
                "running_pid",
                lambda i: (
                    FAKE_PID if i in self.running else None
                ),
            ),
            mock.patch.object(
                subprocess, "run", self._fake_run
            ),
        ]
        for p in self._patches:
            p.start()
        self.shell = NxSigShell()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        storage.DB_DIR = self._db_dir
        self._tmp.cleanup()

    # ---------------- fakes ----------------

    def _fake_start(self, ladder_id):
        if storage.ladder_get(ladder_id) is None:
            raise ladder.LadderError(
                f"no ladder {ladder_id}, see 'ls ladder'"
            )
        self.running.add(ladder_id)
        return FAKE_PID

    def _fake_stop(self, ladder_id):
        was_running = ladder_id in self.running
        self.running.discard(ladder_id)
        return was_running

    def _fake_run(self, args, **kwargs):
        self.mtsig_calls.append(args)
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=f"mtsig {args[-1]}: ok\n",
            stderr="",
        )

    # ---------------- helpers ----------------

    def run_cmd(self, line, answer=None):
        """run one shell command and return what it
        printed; answer is typed at a y/N question,
        EOFError stands for Ctrl+D"""

        def fake_input(prompt):
            # the question is part of the output
            print(prompt, end="")
            if answer is None:
                self.fail(f"'{line}' asked: {prompt}")
            if answer is EOFError:
                raise EOFError
            # the terminal echoes the answer and Enter
            print(answer)
            return answer

        out = io.StringIO()
        with redirect_stdout(out), mock.patch(
            "builtins.input", fake_input
        ):
            self.shell.onecmd(self.shell.precmd(line))
        text = out.getvalue()
        for row in text.splitlines():
            self.assertLessEqual(
                len(row),
                WIDTH,
                f"too wide in '{line}': {row!r}",
            )
        return text

    def lines(self, line, answer=None):
        """the printed lines without the empty ones"""
        return [
            l.rstrip()
            for l in self.run_cmd(line, answer).splitlines()
            if l.strip()
        ]

    def complete(self, line):
        """tab completion for the last word of line"""
        command, _, rest = line.partition(" ")
        text = (
            "" if line.endswith(" ") else line.split()[-1]
        )
        complete = getattr(
            self.shell, f"complete_{command}"
        )
        return complete(text, line, 0, len(line))

    # ---------------- transactions ----------------

    def test_tr_add(self):
        self.assertEqual(
            self.lines("tr add soxl buy 10 20.5"),
            ["added BUY 10 SOXL @ 20.5"],
        )
        self.assertEqual(
            storage.transactions_total_get(
                storage.Stock.SOXL
            ),
            (10, 20.5),
        )

    def test_tr_add_errors(self):
        usage = [
            "usage: tr add <stock> <buy|sell> <count> "
            "<price>"
        ]
        self.assertEqual(
            self.lines("tr add SOXL buy 10"), usage
        )
        self.assertIn(
            "unknown stock 'XXX'",
            self.run_cmd("tr add XXX buy 10 20"),
        )
        self.assertIn(
            "unknown transaction type 'hold'",
            self.run_cmd("tr add SOXL hold 10 20"),
        )
        self.assertIn(
            "invalid literal",
            self.run_cmd("tr add SOXL buy ten 20"),
        )
        self.assertEqual(
            self.lines("tr add SOXL buy 0 20"),
            ["error: count and price must be positive"],
        )
        self.assertEqual(
            storage.transactions_get_all(
                storage.Stock.SOXL
            ),
            [],
        )

    def test_tr_get(self):
        self.run_cmd("tr add SOXL buy 10 20")
        self.run_cmd("tr add SOXL buy 10 30")
        out = self.lines("tr get SOXL")
        self.assertEqual(
            out[0],
            "  Id |     Date |  Time | Type | Count"
            " | Price",
        )
        self.assertEqual(out[1], "-" * WIDTH)
        self.assertRegex(
            out[2],
            r"^   1 \| \d\d\.\d\d\.\d\d \| \d\d:\d\d \|"
            r"  BUY \|    10 \| 20.00$",
        )
        self.assertRegex(out[3], r"^   2 \| .* 30.00$")
        self.assertEqual(out[4], "-" * WIDTH)
        self.assertEqual(
            out[5],
            "total: 20 SOXL, avg buy 25.00, sum 500.00",
        )
        # ls <stock> and the long name do the same
        self.assertEqual(self.lines("ls soxl"), out)
        self.assertEqual(
            self.lines("transactions get SOXL"), out
        )

    def test_tr_get_empty(self):
        self.assertEqual(
            self.lines("tr get MRVU"),
            ["no transactions for MRVU"],
        )

    def test_tr_del_last(self):
        self.run_cmd("tr add SOXL buy 10 20")
        self.run_cmd("tr add SOXL sell 4 25")
        out = self.lines("tr del-last SOXL", "y")
        self.assertRegex(out[2], r"^   2 \| .* SELL \|")
        self.assertEqual(
            out[3:],
            [
                "delete this SOXL transaction? [y/N] y",
                "deleted SOXL transaction 2",
            ],
        )
        self.assertEqual(
            len(
                storage.transactions_get_all(
                    storage.Stock.SOXL
                )
            ),
            1,
        )

    def test_tr_del_last_cancel(self):
        self.run_cmd("tr add SOXL buy 10 20")
        for answer in ("n", "", EOFError):
            out = self.lines("tr del-last SOXL", answer)
            self.assertEqual(out[-1], "cancelled")
        self.assertEqual(
            len(
                storage.transactions_get_all(
                    storage.Stock.SOXL
                )
            ),
            1,
        )
        self.assertEqual(
            self.lines("tr del-last MUU"),
            ["no transactions for MUU"],
        )

    def test_tr_usage(self):
        self.assertEqual(
            self.lines("tr"),
            ["usage: tr [add/get/del-last] ..."],
        )
        self.assertEqual(
            self.lines("tr del SOXL 1"),
            [
                "unknown subcommand 'del', expected",
                "  add/get/del-last",
            ],
        )

    # ---------------- ls, status, xtop ----------------

    def test_ls_totals(self):
        self.assertEqual(
            self.lines("ls"), ["no stocks held"]
        )
        self.run_cmd("tr add SOXL buy 10 20")
        self.run_cmd("tr add MUU buy 2 50")
        self.prices = {"SOXL": 22}
        self.assertEqual(
            self.lines("ls"),
            [
                "Name  | Count | Avg Price |    Total | "
                "Growth %",
                "-" * WIDTH,
                "MUU   |     2 |     50.00 |   100.00 | "
                "       -",
                "SOXL  |    10 |     20.00 |   200.00 | "
                " +10.00%",
            ],
        )

    def test_prices_error(self):
        self.run_cmd("tr add SOXL buy 10 20")

        def missing_key():
            raise KeyError("APCA_API_KEY_ID")

        with mock.patch.object(
            trade_engine, "_headers", missing_key
        ):
            out = self.lines("ls")
        self.assertEqual(
            out[:2],
            [
                "error: missing APCA_API_KEY_ID in .env, "
                "can't",
                "  get current prices",
            ],
        )
        # the table is still shown, without prices
        self.assertTrue(out[-1].endswith("       -"))

    def test_status(self):
        self.assertEqual(
            self.lines("status"),
            ["no stocks held", "mail watcher: not started"],
        )
        self.run_cmd("tr add SOXL buy 10 20")
        self.prices = {"SOXL": 22}
        self.assertEqual(
            self.lines("status"),
            [
                "Name  | Count | Avg Price |    Price | "
                "    State",
                "-" * WIDTH,
                "SOXL  |    10 |     20.00 |    22.00 | "
                "   +20.00",
                "-" * WIDTH,
                "mail watcher: not started",
            ],
        )
        self.assertEqual(
            self.lines("status now"), ["usage: status"]
        )

    def test_status_watcher(self):
        now = datetime.now()
        storage.watcher_status_set(
            {
                "state": "waiting",
                "updated": now.isoformat(),
                "last_order": "BUY 10 SOXL",
            }
        )
        self.assertEqual(
            self.lines("status")[-2:],
            [
                f"mail watcher: running, checked "
                f"{now:%H:%M}, last order",
                "  BUY 10 SOXL",
            ],
        )

    def test_xtop_checks(self):
        self.assertEqual(
            self.lines("xtop 1 2"), ["usage: xtop [sec]"]
        )
        self.assertEqual(
            self.lines("xtop 0.5"),
            [
                "error: seconds must be a number >= 1, "
                "got '0.5'"
            ],
        )
        self.assertEqual(
            self.lines("xtop"), ["no stocks held"]
        )

    def test_xtop_table(self):
        self.run_cmd("tr add SOXL buy 10 20")
        self.run_cmd("tr add MUU buy 2 50")
        updated = datetime(2026, 1, 2, 9, 30, 5)
        lines = _xtop_lines(
            {"SOXL": 22},
            None,
            updated,
            5,
            False,
            ["a note"],
        )
        self.assertEqual(
            lines,
            [
                "Name   Qty      Avg    Price      Gain"
                "   Gain %",
                "-" * WIDTH,
                "MUU      2    50.00        -         -"
                "        -",
                "SOXL    10    20.00    22.00    +20.00"
                "  +10.00%",
                "-" * WIDTH,
                "total                           +20.00"
                "  +10.00%",
                "updated 09:30:05, every 5s, "
                "Ctrl+C to stop",
                "a note",
            ],
        )
        for line in lines:
            self.assertLessEqual(len(line), WIDTH)

    # ---------------- rules ----------------

    def test_rules(self):
        self.assertEqual(
            self.lines("rules"),
            [
                "no rules yet, add one with 'rules add "
                "<rule>'"
            ],
        )
        self.assertEqual(
            self.lines("rules add never buy on a gap up"),
            ["added rule 1"],
        )
        long_rule = "sell half " * 8
        self.run_cmd(f"rules add {long_rule}")
        out = self.lines("rules")
        self.assertEqual(out[0], "  Id | Rule")
        self.assertEqual(
            out[2], "   1 | never buy on a gap up"
        )
        # a long rule wraps inside the Rule column
        self.assertTrue(out[3].startswith("   2 | sell"))
        self.assertTrue(out[4].startswith("     | "))
        self.assertEqual(
            self.lines("rules delete 1"),
            ["deleted rule 1: never buy on a gap up"],
        )
        # the remaining rules are renumbered
        self.assertTrue(
            self.lines("rules")[2].startswith("   1 | sell")
        )

    def test_rules_errors(self):
        self.assertEqual(
            self.lines("rules add"),
            ["usage: rules add <rule>"],
        )
        self.assertEqual(
            self.lines("rules delete x"),
            ["usage: rules delete <id>"],
        )
        self.assertEqual(
            self.lines("rules delete 5"),
            ["error: no rule with Id 5"],
        )
        self.assertEqual(
            self.lines("rules rm 1"),
            [
                "unknown subcommand 'rm', expected "
                "add/delete"
            ],
        )

    # ---------------- base buys ----------------

    def test_bb_add_and_ls(self):
        self.assertEqual(
            self.lines("bb add soxl price 20 count 10"),
            ["added base buy of SOXL: 10 at 20"],
        )
        # the keywords can come in either order
        self.assertEqual(
            self.lines("bb add MUU count 2 price 50.5"),
            ["added base buy of MUU: 2 at 50.5"],
        )
        self.assertEqual(
            self.lines("bb add SOXL price 18 count 5"),
            ["replaced base buy of SOXL: 5 at 18"],
        )
        self.prices = {"SOXL": 19.8}
        # in config order: MUU before SOXL
        self.assertEqual(
            self.lines("bb ls"),
            [
                "Name     Qty         Buy       Price"
                "    Change %",
                "-" * WIDTH,
                "MUU        2       50.50           -"
                "           -",
                "SOXL       5       18.00       19.80"
                "     +10.00%",
            ],
        )

    def test_bb_errors(self):
        usage = [
            "usage: bb add <stock> price <price> count",
            "  <count>",
        ]
        for line in (
            "bb add SOXL price 20",
            "bb add SOXL price 20 qty 10",
            "bb add SOXL price 20 price 10",
        ):
            self.assertEqual(self.lines(line), usage)
        self.assertEqual(
            self.lines("bb add SOXL price x count 1"),
            [
                "error: price must be a number and count "
                "a whole",
                "  number",
            ],
        )
        self.assertEqual(
            self.lines("bb add SOXL price 20 count -1"),
            ["error: price and count must be positive"],
        )
        self.assertIn(
            "unknown stock 'XXX'",
            self.run_cmd("bb add XXX price 1 count 1"),
        )
        self.assertEqual(
            self.lines("bb ls"),
            [
                "no base buys yet, add one with 'bb add "
                "<stock>",
                "  price <price> count <count>'",
            ],
        )
        self.assertEqual(
            self.lines("bb ls all"), ["usage: bb ls"]
        )
        self.assertEqual(
            self.lines("bb del SOXL"),
            [
                "unknown action 'del' for bb, expected "
                "add/ls/rm"
            ],
        )

    def test_bb_rm(self):
        self.run_cmd("bb add SOXL price 20 count 10")
        self.assertEqual(
            self.lines("bb rm SOXL", "n"),
            [
                "delete base buy of SOXL: 10 at 20? "
                "[y/N] n",
                "cancelled",
            ],
        )
        self.assertEqual(
            self.lines("bb rm soxl", "y"),
            [
                "delete base buy of SOXL: 10 at 20? "
                "[y/N] y",
                "deleted base buy of SOXL",
            ],
        )
        self.assertEqual(storage.base_buys_get_all(), [])
        self.assertEqual(
            self.lines("bb rm SOXL"),
            ["error: no base buy of SOXL, see 'bb ls'"],
        )

    def test_bb_help(self):
        # a bare bb shows its help
        self.assertEqual(
            self.run_cmd("bb"), self.run_cmd("help bb")
        )
        self.assertIn("bb add <stock>", self.run_cmd("bb"))

    # ---------------- ladders ----------------

    def test_run_ladder(self):
        self.assertEqual(
            self.lines("run ladder soxl down 10 100"),
            [
                "ladder 1 saved: SOXL down every 10 from "
                "100",
                "starting ladder 1...",
                f"ladder 1 started (pid {FAKE_PID}), next "
                "alert at 90",
            ],
        )
        self.assertEqual(self.running, {1})
        saved = storage.ladder_get(1)
        self.assertEqual(
            (saved["Stock"], saved["Direction"]),
            ("SOXL", "down"),
        )
        self.assertEqual(
            (saved["Step"], saved["From"]), (10, 100)
        )

    def test_run_ladder_errors(self):
        usage = [
            "usage: run ladder <stock> <down|up> <step>",
            "  <price>, or run ladder <id>",
        ]
        self.assertEqual(
            self.lines("run ladder SOXL down 10"), usage
        )
        self.assertEqual(self.lines("run ladder x"), usage)
        self.assertEqual(
            self.lines("run ladder SOXL left 10 100"),
            [
                "error: unknown direction 'left', expected",
                "  down/up",
            ],
        )
        self.assertEqual(
            self.lines("run ladder SOXL down x 100"),
            ["error: step and price must be numbers"],
        )
        self.assertEqual(
            self.lines("run ladder SOXL down 100 100"),
            [
                "error: a down ladder needs a step smaller "
                "than",
                "  its price",
            ],
        )
        self.assertEqual(
            self.lines("run ladder 3"),
            [
                "starting ladder 3...",
                "error: no ladder 3, see 'ls ladder'",
            ],
        )
        with mock.patch.dict(os.environ):
            del os.environ["TOKEN"]
            self.assertEqual(
                self.lines("run ladder SOXL up 5 100"),
                [
                    "error: Telegram isn't set up, add "
                    "TOKEN and",
                    "  CHAT_ID to .env",
                ],
            )
        self.assertEqual(storage.ladders_get_all(), [])
        self.assertEqual(
            self.lines("run"),
            [
                "usage: run ladder <stock> <down|up> "
                "<step>",
                "  <price>, run ladder <id>, run "
                "mail-broker",
            ],
        )
        self.assertEqual(
            self.lines("run x"),
            [
                "unknown task 'x', expected "
                "ladder/mail-broker"
            ],
        )

    def test_ls_ladder(self):
        self.assertEqual(
            self.lines("ls ladder"),
            ["no ladders saved, see 'help run'"],
        )
        self.run_cmd("run ladder SOXL down 10 100")
        self.run_cmd("run ladder MRVU up 2.5 40")
        self.run_cmd("stop ladder 2")
        header = [
            "Id  Stock  Ladder        From     Next  State",
            "-" * WIDTH,
        ]
        self.assertEqual(
            self.lines("ls ladder"),
            header
            + [
                " 1  SOXL   down 10     100.00    90.00"
                "  running",
                " 2  MRVU   up 2.5       40.00    42.50"
                "  stopped",
            ],
        )
        # a down ladder with no levels left is done
        storage.ladder_set_last(1, 10)
        storage.ladder_status_set(1, {"state": "done"})
        self.running.discard(1)
        self.assertEqual(
            self.lines("ls ladder")[2],
            " 1  SOXL   down 10     100.00        -  done",
        )
        self.assertEqual(
            self.lines("ls ladder 1"),
            ["usage: ls ladder"],
        )

    def test_restart_and_stop_ladder(self):
        self.run_cmd("run ladder SOXL down 10 100")
        self.assertEqual(
            self.lines("stop ladder 1"),
            ["ladder 1 stopped"],
        )
        self.assertEqual(
            self.lines("stop ladder 1"),
            ["ladder 1 is not running"],
        )
        self.assertEqual(
            self.lines("run ladder 1"),
            [
                "starting ladder 1...",
                f"ladder 1 started (pid {FAKE_PID}), next "
                "alert at 90",
            ],
        )
        self.assertEqual(
            self.lines("stop ladder"),
            ["usage: stop ladder <id>"],
        )
        self.assertEqual(
            self.lines("stop"),
            ["usage: stop ladder <id>, stop mail-broker"],
        )
        self.assertEqual(
            self.lines("stop x"),
            [
                "unknown task 'x', expected "
                "ladder/mail-broker"
            ],
        )

    def test_rm_ladder(self):
        self.run_cmd("run ladder SOXL down 10 100")
        out = self.lines("rm ladder 1", "n")
        # the ladder is shown before the question
        self.assertTrue(out[0].startswith("Id  Stock"))
        self.assertTrue(out[2].endswith("running"))
        self.assertEqual(
            out[3:],
            [
                "stop and delete ladder 1? [y/N] n",
                "cancelled",
            ],
        )
        self.assertIsNotNone(storage.ladder_get(1))
        self.assertEqual(
            self.lines("rm ladder 1", "y")[3:],
            [
                "stop and delete ladder 1? [y/N] y",
                "ladder 1 stopped and deleted",
            ],
        )
        self.assertIsNone(storage.ladder_get(1))
        self.assertEqual(self.running, set())

        # a stopped ladder is only deleted
        self.run_cmd("run ladder SOXL up 10 100")
        self.run_cmd("stop ladder 1")
        self.assertEqual(
            self.lines("rm ladder 1", "y")[3:],
            [
                "delete ladder 1? [y/N] y",
                "ladder 1 deleted",
            ],
        )
        self.assertEqual(storage.ladders_get_all(), [])

    def test_rm_ladder_errors(self):
        self.assertEqual(
            self.lines("rm ladder 1"),
            ["error: no ladder 1, see 'ls ladder'"],
        )
        for line in ("rm", "rm ladder", "rm ladder x"):
            self.assertEqual(
                self.lines(line), ["usage: rm ladder <id>"]
            )

    # ---------------- mail broker, ps ----------------

    def test_mail_broker(self):
        self.assertEqual(
            self.lines("run mail-broker"),
            [
                "starting the mail broker...",
                "mtsig start: ok",
            ],
        )
        self.assertEqual(
            self.lines("stop mail-broker"),
            [
                "stopping the mail broker...",
                "mtsig stop: ok",
            ],
        )
        mtsig = os.path.join(storage.ROOT_DIR, "mtsig")
        self.assertEqual(
            self.mtsig_calls,
            [[mtsig, "start"], [mtsig, "stop"]],
        )
        self.assertEqual(
            self.lines("run mail-broker now"),
            ["usage: run mail-broker"],
        )
        self.assertEqual(
            self.lines("stop mail-broker now"),
            ["usage: stop mail-broker"],
        )

    def test_ps(self):
        self.assertEqual(
            self.lines("ps"),
            ["no background tasks running"],
        )
        self.run_cmd("run ladder SOXL down 10 100")
        now = datetime.now()
        storage.ladder_status_set(
            1,
            {
                "pid": FAKE_PID,
                "started": now.isoformat(),
                "updated": now.isoformat(),
                "state": "waiting",
            },
        )
        # the pid file of ./mtsig start
        with open(
            os.path.join(storage.DB_DIR, "mtsig.pid"), "w"
        ) as f:
            f.write("777\n")
        storage.watcher_status_set(
            {
                "pid": 777,
                "started": now.isoformat(),
                "updated": now.isoformat(),
                "state": "connected",
            }
        )
        started = f"{now:%d.%m %H:%M}"
        with mock.patch.object(
            ladder, "process_runs", lambda *a: True
        ):
            out = self.lines("ps")
        self.assertEqual(
            out,
            [
                "Id  Task             PID  Started      "
                "State",
                "-" * WIDTH,
                f" -  mail-broker      777  {started}  "
                "connected",
                f" 1  ladder SOXL     {FAKE_PID}  "
                f"{started}  "
                "waiting",
            ],
        )
        self.assertEqual(self.lines("ps -a"), ["usage: ps"])

    # ------------- strategy, help, shell -------------

    def test_strategy(self):
        self.assertEqual(
            self.lines("strategy run"),
            ["strategy run: not implemented yet"],
        )
        self.assertEqual(
            self.lines("strategy"),
            ["usage: strategy [run/stop/list/get]"],
        )

    def test_help(self):
        out = self.run_cmd("help")
        for command in ("tr add", "bb add", "run ladder"):
            self.assertIn(command, out)
        self.assertEqual(
            self.lines("help nothing"),
            ["no help on 'nothing'"],
        )
        # every command has a help text that fits WIDTH
        for name in self.shell.get_names():
            if name.startswith("do_") and name != "do_EOF":
                self.assertTrue(
                    self.run_cmd(
                        f"help {name[3:]}"
                    ).strip(),
                    name,
                )

    def test_unknown_command(self):
        self.assertEqual(
            self.lines("buy SOXL"),
            [
                "unknown command: buy. Type 'help' for "
                "commands."
            ],
        )
        # an empty line does nothing
        self.assertEqual(self.run_cmd(""), "")

    def test_exit(self):
        for line in ("exit", "quit", "q"):
            self.assertTrue(self.shell.onecmd(line))

    # ---------------- completion ----------------

    def test_complete(self):
        self.assertEqual(
            self.complete("tr "), ["add", "get", "del-last"]
        )
        self.assertEqual(self.complete("tr a"), ["add"])
        self.assertEqual(
            self.complete("tr add so"), ["SOXL"]
        )
        self.assertEqual(
            self.complete("tr add SOXL "), ["buy", "sell"]
        )
        self.assertEqual(self.complete("tr get SOXL "), [])
        self.assertEqual(self.complete("ls l"), ["ladder"])
        self.assertEqual(
            self.complete("rules "), ["add", "delete"]
        )
        self.assertEqual(
            self.complete("bb add MUU "),
            ["price", "count"],
        )
        self.assertEqual(
            self.complete("bb add MUU price 2 c"),
            ["count"],
        )
        self.assertEqual(
            self.complete("run "),
            ["ladder", "mail-broker"],
        )
        self.assertEqual(
            self.complete("run ladder SOXL "),
            ["down", "up"],
        )
        self.assertEqual(
            self.complete("strategy "),
            ["run", "stop", "list", "get"],
        )

    def test_complete_saved(self):
        self.run_cmd("bb add MUU price 2 count 1")
        self.assertEqual(self.complete("bb rm "), ["MUU"])
        self.run_cmd("run ladder SOXL down 10 100")
        self.run_cmd("run ladder SOXL up 10 100")
        self.run_cmd("stop ladder 1")
        self.assertEqual(
            self.complete("rm ladder "), ["1", "2"]
        )
        # stop offers only the running ladders
        self.assertEqual(
            self.complete("stop ladder "), ["2"]
        )


if __name__ == "__main__":
    unittest.main()

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
# the tests pin down what the commands print, so a
# change of the shell shows what it changes.

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
                f"no ladder {ladder_id}, see 'ls ladders'"
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

    # ---------------- trades ----------------

    def test_add_trade(self):
        self.assertEqual(
            self.lines(
                "add trade soxl buy count 10 price 20.5"
            ),
            ["added BUY 10 SOXL @ 20.5"],
        )
        # the keywords in either order
        self.assertEqual(
            self.lines(
                "add trade SOXL sell price 22 count 4"
            ),
            ["added SELL 4 SOXL @ 22"],
        )
        self.assertEqual(
            storage.trades_total_get(storage.Stock.SOXL),
            (6, 20.5),
        )

    def test_add_trade_errors(self):
        usage = [
            "usage: add trade <stock> <buy|sell> count",
            "  <count> price <price>",
        ]
        for line in (
            "add trade SOXL buy 10 20",
            "add trade SOXL buy count 10",
            "add trade SOXL buy count 10 count 2",
            "add trade SOXL buy count 10 qty 2",
            "add trade",
        ):
            self.assertEqual(self.lines(line), usage, line)
        self.assertIn(
            "unknown stock 'XXX'",
            self.run_cmd(
                "add trade XXX buy count 1 price 2"
            ),
        )
        self.assertIn(
            "unknown trade type 'hold'",
            self.run_cmd(
                "add trade SOXL hold count 1 price 2"
            ),
        )
        self.assertEqual(
            self.lines(
                "add trade SOXL buy count x price 2"
            ),
            [
                "error: count must be a whole number and "
                "price a",
                "  number",
            ],
        )
        self.assertEqual(
            self.lines(
                "add trade SOXL buy count 0 price 2"
            ),
            ["error: count and price must be positive"],
        )
        self.assertEqual(
            storage.trades_get_all(storage.Stock.SOXL), []
        )

    def test_ls_trades_of_a_stock(self):
        self.run_cmd("add trade SOXL buy count 10 price 20")
        self.run_cmd("add trade SOXL buy count 10 price 30")
        out = self.lines("ls trades SOXL")
        self.assertEqual(
            out[0],
            "  Id |     Date |  Time | Type | Count "
            "| Price",
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
        self.assertEqual(
            self.lines("ls trades MRVU"),
            ["no trades for MRVU"],
        )
        self.assertEqual(
            self.lines("ls trades SOXL MUU"),
            ["usage: ls trades [<stock>]"],
        )

    def test_ls_trades(self):
        self.assertEqual(
            self.lines("ls trades"),
            ["no trades yet, see 'help add trade'"],
        )
        self.run_cmd("add trade SOXL buy count 10 price 20")
        self.run_cmd("add trade SOXL buy count 10 price 30")
        self.run_cmd("add trade MUU buy count 1 price 50")
        out = self.lines("ls trades")
        self.assertEqual(
            out[:2],
            ["Name  | Trades | Last trade", "-" * WIDTH],
        )
        # in config order
        self.assertRegex(
            out[2],
            r"^MUU   \|      1 \| "
            r"\d\d\.\d\d\.\d\d \d\d:\d\d$",
        )
        self.assertRegex(out[3], r"^SOXL  \|      2 \| ")

    def test_rm_trade(self):
        self.run_cmd("add trade SOXL buy count 10 price 20")
        self.run_cmd("add trade SOXL buy count 10 price 30")
        self.run_cmd("add trade SOXL sell count 4 price 25")
        # any trade, not only the last one
        out = self.lines("rm trade soxl 2", "y")
        self.assertRegex(out[2], r"^   2 \| .*  BUY \|")
        self.assertEqual(
            out[3:],
            [
                "delete SOXL trade 2? [y/N] y",
                "deleted SOXL trade 2",
            ],
        )
        self.assertEqual(
            [
                t["Id"]
                for t in storage.trades_get_all(
                    storage.Stock.SOXL
                )
            ],
            [1, 3],
        )
        # the total is rebuilt from the trades left
        self.assertEqual(
            storage.trades_total_get(storage.Stock.SOXL),
            (6, 20.0),
        )

    def test_rm_trade_cancel_and_errors(self):
        self.run_cmd("add trade SOXL buy count 10 price 20")
        for answer in ("n", "", EOFError):
            out = self.lines("rm trade SOXL 1", answer)
            self.assertEqual(out[-1], "cancelled")
        self.assertEqual(
            len(storage.trades_get_all(storage.Stock.SOXL)),
            1,
        )
        self.assertEqual(
            self.lines("rm trade SOXL 5"),
            [
                "error: no SOXL trade 5, see "
                "'ls trades SOXL'"
            ],
        )
        for line in ("rm trade SOXL", "rm trade SOXL x"):
            self.assertEqual(
                self.lines(line),
                ["usage: rm trade <stock> <id>"],
            )
        self.assertIn(
            "unknown stock 'XXX'",
            self.run_cmd("rm trade XXX 1"),
        )

    # ---------------- stocks, status, xtop ----------------

    def test_ls_stocks(self):
        self.assertEqual(
            self.lines("ls stocks"), ["no stocks held"]
        )
        self.run_cmd("add trade SOXL buy count 10 price 20")
        self.run_cmd("add trade MUU buy count 2 price 50")
        self.prices = {"SOXL": 22}
        self.assertEqual(
            self.lines("ls stocks"),
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
        # one stock's details are its trades
        self.assertEqual(
            self.lines("ls stocks soxl"),
            ["use 'ls trades SOXL'"],
        )
        self.assertEqual(
            self.lines("ls stocks SOXL MUU"),
            ["usage: ls stocks"],
        )

    def test_prices_error(self):
        self.run_cmd("add trade SOXL buy count 10 price 20")

        def missing_key():
            raise KeyError("APCA_API_KEY_ID")

        with mock.patch.object(
            trade_engine, "_headers", missing_key
        ):
            out = self.lines("ls stocks")
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
        self.run_cmd("add trade SOXL buy count 10 price 20")
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
        self.run_cmd("add trade SOXL buy count 10 price 20")
        self.run_cmd("add trade MUU buy count 2 price 50")
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

    # ---------------- rules ----------------

    def test_rules(self):
        self.assertEqual(
            self.lines("ls rules"),
            [
                "no rules yet, add one with 'add rule "
                "<rule>'"
            ],
        )
        self.assertEqual(
            self.lines("add rule never buy on a gap up"),
            ["added rule 1"],
        )
        long_rule = "sell half " * 8
        self.run_cmd(f"add rule {long_rule}")
        out = self.lines("ls rules")
        self.assertEqual(out[0], "  Id | Rule")
        self.assertEqual(
            out[2], "   1 | never buy on a gap up"
        )
        # a long rule wraps inside the Rule column
        self.assertTrue(out[3].startswith("   2 | sell"))
        self.assertTrue(out[4].startswith("     | "))
        self.assertEqual(
            self.lines("rm rule 1", "y"),
            [
                "Id | Rule".rjust(11),
                "-" * WIDTH,
                "   1 | never buy on a gap up",
                "delete rule 1? [y/N] y",
                "deleted rule 1",
            ],
        )
        # the rules after it are renumbered
        self.assertTrue(
            self.lines("ls rules")[2].startswith(
                "   1 | sell"
            )
        )
        self.assertEqual(
            self.lines("rm rule 1", "n")[-1], "cancelled"
        )

    def test_rules_errors(self):
        self.assertEqual(
            self.lines("add rule"),
            ["usage: add rule <rule>"],
        )
        for line in ("rm rule", "rm rule x", "rm rule 1 2"):
            self.assertEqual(
                self.lines(line), ["usage: rm rule <id>"]
            )
        self.assertEqual(
            self.lines("rm rule 5"),
            ["error: no rule 5, see 'ls rules'"],
        )
        self.assertEqual(
            self.lines("ls rules all"), ["usage: ls rules"]
        )

    # ---------------- basetrades ----------------

    def test_basetrades(self):
        self.assertEqual(
            self.lines(
                "add basetrade soxl price 20 count 10"
            ),
            ["added basetrade of SOXL: 10 at 20"],
        )
        # the keywords in either order
        self.assertEqual(
            self.lines(
                "add basetrade MUU count 2 price 50.5"
            ),
            ["added basetrade of MUU: 2 at 50.5"],
        )
        self.assertEqual(
            self.lines(
                "add basetrade SOXL price 18 count 5"
            ),
            ["replaced basetrade of SOXL: 5 at 18"],
        )
        self.prices = {"SOXL": 19.8}
        # in config order: MUU before SOXL
        self.assertEqual(
            self.lines("ls basetrades"),
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

    def test_basetrade_errors(self):
        usage = [
            "usage: add basetrade <stock> price <price> "
            "count",
            "  <count>",
        ]
        for line in (
            "add basetrade SOXL price 20",
            "add basetrade SOXL price 20 qty 10",
            "add basetrade SOXL price 20 price 10",
            "add basetrade",
        ):
            self.assertEqual(self.lines(line), usage, line)
        self.assertEqual(
            self.lines(
                "add basetrade SOXL price x count 1"
            ),
            [
                "error: price must be a number and count "
                "a whole",
                "  number",
            ],
        )
        self.assertEqual(
            self.lines(
                "add basetrade SOXL price 2 count -1"
            ),
            ["error: price and count must be positive"],
        )
        self.assertIn(
            "unknown stock 'XXX'",
            self.run_cmd(
                "add basetrade XXX price 1 count 1"
            ),
        )
        self.assertEqual(
            self.lines("ls basetrades"),
            ["no basetrades yet, see 'help add basetrade'"],
        )
        self.assertEqual(
            self.lines("ls basetrades all"),
            ["usage: ls basetrades"],
        )

    def test_rm_basetrade(self):
        self.run_cmd("add basetrade SOXL price 20 count 10")
        self.assertEqual(
            self.lines("rm basetrade SOXL", "n"),
            [
                "delete basetrade of SOXL: 10 at 20? "
                "[y/N] n",
                "cancelled",
            ],
        )
        self.assertEqual(
            self.lines("rm basetrade soxl", "y"),
            [
                "delete basetrade of SOXL: 10 at 20? "
                "[y/N] y",
                "deleted basetrade of SOXL",
            ],
        )
        self.assertEqual(storage.basetrades_get_all(), [])
        self.assertEqual(
            self.lines("rm basetrade SOXL"),
            [
                "error: no basetrade of SOXL, see "
                "'ls basetrades'"
            ],
        )
        self.assertEqual(
            self.lines("rm basetrade"),
            ["usage: rm basetrade <stock>"],
        )

    # ---------------- ladders ----------------

    def test_add_ladder(self):
        self.assertEqual(
            self.lines("add ladder soxl down 10 from 100"),
            [
                "ladder 1 saved: SOXL down every 10 from "
                "100",
                "start it with 'run ladder 1'",
            ],
        )
        self.assertEqual(self.running, set())
        saved = storage.ladder_get(1)
        self.assertEqual(
            (saved["Stock"], saved["Direction"]),
            ("SOXL", "down"),
        )
        self.assertEqual(
            (saved["Step"], saved["From"]), (10, 100)
        )
        # run as the last word starts it too
        self.assertEqual(
            self.lines(
                "add ladder MRVU up 2.5 FROM 40 run"
            ),
            [
                "ladder 2 saved: MRVU up every 2.5 from 40",
                "starting ladder 2...",
                f"ladder 2 started (pid {FAKE_PID}), next "
                "alert at 42.5",
            ],
        )
        self.assertEqual(self.running, {2})

    def test_add_ladder_errors(self):
        usage = [
            "usage: add ladder <stock> <down|up> <step> "
            "from",
            "  <price> [run]",
        ]
        for line in (
            "add ladder SOXL down 10 100",
            "add ladder SOXL down 10 to 100",
            "add ladder SOXL down 10 from 100 now",
            "add ladder SOXL down 10 from",
            "add ladder",
        ):
            self.assertEqual(self.lines(line), usage, line)
        self.assertEqual(
            self.lines("add ladder SOXL left 10 from 100"),
            [
                "error: unknown direction 'left', expected",
                "  down/up",
            ],
        )
        self.assertEqual(
            self.lines("add ladder SOXL down x from 100"),
            ["error: step and price must be numbers"],
        )
        self.assertEqual(
            self.lines("add ladder SOXL down 100 from 100"),
            [
                "error: a down ladder needs a step smaller "
                "than",
                "  its price",
            ],
        )
        with mock.patch.dict(os.environ):
            del os.environ["TOKEN"]
            self.assertEqual(
                self.lines("add ladder SOXL up 5 from 100"),
                [
                    "error: Telegram isn't set up, add "
                    "TOKEN and",
                    "  CHAT_ID to .env",
                ],
            )
        self.assertEqual(storage.ladders_get_all(), [])

    def test_run_and_stop_ladder(self):
        self.run_cmd("add ladder SOXL down 10 from 100")
        self.assertEqual(
            self.lines("run ladder 1"),
            [
                "starting ladder 1...",
                f"ladder 1 started (pid {FAKE_PID}), next "
                "alert at 90",
            ],
        )
        self.assertEqual(
            self.lines("stop ladder 1"),
            ["ladder 1 stopped"],
        )
        self.assertEqual(
            self.lines("stop ladder 1"),
            ["ladder 1 is not running"],
        )
        for line in ("run ladder", "run ladder SOXL down"):
            self.assertEqual(
                self.lines(line), ["usage: run ladder <id>"]
            )
        self.assertEqual(
            self.lines("run ladder 3"),
            [
                "starting ladder 3...",
                "error: no ladder 3, see 'ls ladders'",
            ],
        )
        self.assertEqual(
            self.lines("stop ladder"),
            ["usage: stop ladder <id>"],
        )

    def test_ls_ladders(self):
        self.assertEqual(
            self.lines("ls ladders"),
            ["no ladders yet, see 'help add ladder'"],
        )
        self.run_cmd("add ladder SOXL down 10 from 100 run")
        self.run_cmd("add ladder MRVU up 2.5 from 40")
        header = [
            "Id  Stock  Ladder        From     Next  State",
            "-" * WIDTH,
        ]
        self.assertEqual(
            self.lines("ls ladders"),
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
            self.lines("ls ladders")[2],
            " 1  SOXL   down 10     100.00        -  done",
        )
        self.assertEqual(
            self.lines("ls ladders 1"),
            ["usage: ls ladders"],
        )

    def test_rm_ladder(self):
        self.run_cmd("add ladder SOXL down 10 from 100 run")
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
        self.run_cmd("add ladder SOXL up 10 from 100")
        self.assertEqual(
            self.lines("rm ladder 1", "y")[3:],
            [
                "delete ladder 1? [y/N] y",
                "ladder 1 deleted",
            ],
        )
        self.assertEqual(storage.ladders_get_all(), [])
        self.assertEqual(
            self.lines("rm ladder 1"),
            ["error: no ladder 1, see 'ls ladders'"],
        )
        for line in ("rm ladder", "rm ladder x"):
            self.assertEqual(
                self.lines(line), ["usage: rm ladder <id>"]
            )

    # ---------------- mail broker, tasks ----------------

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

    def test_ls_tasks(self):
        self.assertEqual(
            self.lines("ls tasks"),
            ["no background tasks running"],
        )
        self.run_cmd("add ladder SOXL down 10 from 100 run")
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
            out = self.lines("ls tasks")
        self.assertEqual(
            out,
            [
                "Id  Task             PID  Started      "
                "State",
                "-" * WIDTH,
                f" 1  ladder SOXL     {FAKE_PID}  "
                f"{started}  waiting",
                f" -  mail-broker      777  {started}  "
                "connected",
            ],
        )
        self.assertEqual(
            self.lines("ls tasks -a"), ["usage: ls tasks"]
        )

    # ---------------- the action commands ----------------

    def test_bare_action_lists_objects(self):
        self.assertEqual(
            self.lines("ls"),
            [
                "ls: stocks, trades, ladders, rules, "
                "basetrades,",
                "  tasks",
            ],
        )
        self.assertEqual(
            self.lines("add"),
            ["add: trade, ladder, rule, basetrade"],
        )
        self.assertEqual(
            self.lines("rm"),
            ["rm: trade, ladder, rule, basetrade"],
        )
        self.assertEqual(
            self.lines("run"), ["run: ladder, mail-broker"]
        )
        self.assertEqual(
            self.lines("stop"),
            ["stop: ladder, mail-broker"],
        )

    def test_action_errors(self):
        self.assertEqual(
            self.lines("rm x 1"),
            [
                "unknown object 'x' for rm, expected",
                "  trade/ladder/rule/basetrade",
            ],
        )
        self.assertEqual(
            self.lines("run trade"),
            ["trade has no run, it has ls/add/rm"],
        )
        self.assertEqual(
            self.lines("ls mail-broker"),
            ["mail-broker has no ls, it has run/stop"],
        )
        # plural after ls, singular everywhere else
        self.assertEqual(
            self.lines("ls ladder"), ["use 'ls ladders'"]
        )
        self.assertEqual(
            self.lines("rm ladders 1"),
            ["use 'rm ladder 1'"],
        )
        self.assertEqual(
            self.lines("add trades SOXL buy"),
            ["use 'add trade SOXL buy'"],
        )
        # the old commands are gone
        for old in ("tr", "bb", "rules", "ps"):
            self.assertIn(
                f"unknown command: {old}.",
                self.run_cmd(f"{old} ls"),
            )

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

    def test_help_overview(self):
        out = self.run_cmd("help")
        # the usage of every action of every object
        for module in self.shell.objects.values():
            for action in module.actions():
                word = (
                    module.plural
                    if action == "ls"
                    else module.name
                )
                self.assertIn(f"  {action} {word}", out)
        for command in ("status", "xtop", "strategy"):
            self.assertIn(f"\n  {command}", out)
        # only the usage lines, no descriptions
        self.assertNotIn("Telegram", out)

    def test_help_topics(self):
        self.assertEqual(
            self.lines("help add trade"),
            [
                "add trade <stock> <buy|sell>",
                "  count <count> price <price>",
                "    record a trade, e.g. 'add trade SOXL",
                "    buy count 10 price 20.5'",
            ],
        )
        # an object: all its actions
        out = self.run_cmd("help ladders")
        for usage in (
            "ls ladders",
            "add ladder",
            "rm ladder",
            "run ladder",
            "stop ladder",
        ):
            self.assertIn(usage, out)
        self.assertEqual(out, self.run_cmd("help ladder"))
        # an action: every object that has it
        out = self.run_cmd("help rm")
        for usage in (
            "rm trade",
            "rm ladder",
            "rm rule",
            "rm basetrade",
        ):
            self.assertIn(usage, out)
        self.assertIn(
            "live gain/loss", self.run_cmd("help xtop")
        )
        for topic in ("nothing", "add nothing", "xtop 5"):
            self.assertEqual(
                self.lines(f"help {topic}"),
                [f"no help on '{topic}'"],
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

    # ---------------- the command modules ----------------

    def test_collected_modules(self):
        self.assertEqual(
            list(self.shell.objects),
            [
                "stocks",
                "trade",
                "ladder",
                "rule",
                "basetrade",
                "mail-broker",
                "task",
            ],
        )
        data = ["trade", "ladder", "rule", "basetrade"]
        tasks = ["ladder", "mail-broker"]
        self.assertEqual(
            self.shell.actions,
            {
                "ls": ["stocks"] + data + ["task"],
                "add": data,
                "rm": data,
                "run": tasks,
                "stop": tasks,
            },
        )
        trade = self.shell.objects["trade"]
        self.assertEqual(
            trade.actions(), ["ls", "add", "rm"]
        )
        self.assertFalse(trade.supports("run"))
        self.assertFalse(trade.supports("complete"))

    # ---------------- completion ----------------

    def test_complete(self):
        self.assertEqual(
            self.complete("ls "),
            [
                "stocks",
                "trades",
                "ladders",
                "rules",
                "basetrades",
                "tasks",
            ],
        )
        self.assertEqual(
            self.complete("ls la"), ["ladders"]
        )
        self.assertEqual(
            self.complete("ls trades so"), ["SOXL"]
        )
        self.assertEqual(
            self.complete("add "),
            ["trade", "ladder", "rule", "basetrade"],
        )
        self.assertEqual(
            self.complete("add trade SOXL "),
            ["buy", "sell"],
        )
        self.assertEqual(
            self.complete("add trade SOXL buy "),
            ["count", "price"],
        )
        self.assertEqual(
            self.complete("add trade SOXL buy count 1 p"),
            ["price"],
        )
        self.assertEqual(
            self.complete("add basetrade MUU "),
            ["price", "count"],
        )
        self.assertEqual(
            self.complete("add ladder SOXL "),
            ["down", "up"],
        )
        self.assertEqual(
            self.complete("add ladder SOXL down 10 "),
            ["from"],
        )
        self.assertEqual(
            self.complete(
                "add ladder SOXL down 10 from 1 "
            ),
            ["run"],
        )
        self.assertEqual(
            self.complete("run "), ["ladder", "mail-broker"]
        )
        self.assertEqual(self.complete("run x "), [])
        self.assertEqual(self.complete("help a"), ["add"])
        self.assertEqual(
            self.complete("help add "),
            ["trade", "ladder", "rule", "basetrade"],
        )
        self.assertEqual(
            self.complete("strategy "),
            ["run", "stop", "list", "get"],
        )

    def test_complete_saved(self):
        self.run_cmd("add basetrade MUU price 2 count 1")
        self.assertEqual(
            self.complete("rm basetrade "), ["MUU"]
        )
        self.run_cmd("add trade SOXL buy count 1 price 2")
        self.run_cmd("add trade SOXL buy count 1 price 3")
        self.assertEqual(
            self.complete("rm trade SOXL "), ["1", "2"]
        )
        self.assertEqual(self.complete("rm trade XX "), [])
        self.run_cmd("add rule keep calm")
        self.assertEqual(self.complete("rm rule "), ["1"])
        self.run_cmd("add ladder SOXL down 10 from 100")
        self.run_cmd("add ladder SOXL up 10 from 100 run")
        self.assertEqual(
            self.complete("rm ladder "), ["1", "2"]
        )
        # run offers the stopped ladders, stop the
        # running ones
        self.assertEqual(
            self.complete("run ladder "), ["1"]
        )
        self.assertEqual(
            self.complete("stop ladder "), ["2"]
        )


if __name__ == "__main__":
    unittest.main()

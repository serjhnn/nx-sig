# test_shell: tests of the nxshell commands
#
#   python tests/test_shell.py
#
# every test runs commands through NxSigShell.onecmd()
# against a temporary data folder, so the real data is
# not touched. the prices, Telegram, the ladder and
# alerts processes and ./mtsig are faked: nothing is
# started and nothing is sent. every printed line is
# also checked to fit width().
#
# the fakes replace the engines (prices, ladder,
# subprocess, the .env keys), not names inside the
# shell, so they work wherever the shell code lives.
#
# the tests pin down what the commands print, so a
# change of the shell shows what it changes.
# ConfigTest reads the real config.json: every script
# finds its settings there.

import io
import json
import os
import re
import subprocess
import tempfile
import threading
import unittest
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock

# plain output without color codes
os.environ["NO_COLOR"] = "1"

import paths  # noqa: F401, scripts/ on sys.path
import chart
import config
from engines import alerts, demo, demo_prices, ladder
from engines import prices
from notifiers import notifier
import process
import requests
import shell.alert_cmd
import shell.demo_cmd
import shell.notify_cmd
import shell.overview_cmd
import shell.terminal_cmd
import shell.ui
import storage
import tasks_owner
from notifiers import telegram_notify, termux_notify
from commands import NxSigShell
from engines import basetrades, trades
from engines.trades import Stock, TradeType
from shell.alert_cmd import gain_alert_lines
from shell.overview_cmd import _xtop_lines
from shell.ui import width

FAKE_PID = 4242
# the real bars and latest prices requests, setUp
# fakes them
REAL_BARS = prices._bars
REAL_LATEST = prices._latest_prices
# another device that runs the background tasks
OTHER_OWNER = {
    "id": "other",
    "name": "pc",
    "since": "2026-10-16T14:30:00",
}


USAGE_NOTIFY = (
    "usage: test notify <alert|ladder> [repeat <n>]"
)


class ShellTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._db_dir = storage.DB_DIR
        storage.DB_DIR = self._tmp.name
        # {stock name: price}, what the fake API returns
        self.prices = {}
        # the feed of each latest prices request
        self.feeds = []
        # the ids of the ladders that "run"
        self.running = set()
        # what ./mtsig was called with
        self.mtsig_calls = []
        # [(time, price)] the fake bars request returns,
        # and the requests made
        self.bars = []
        self.bars_calls = []
        # the force of each ladder.start
        self.forced = []
        # the alerts process "runs", and the force of
        # each alerts.start
        self.alerts_running = False
        self.alerts_forced = []
        self._patches = [
            # this device's id, not in the repo folder
            mock.patch.object(
                tasks_owner,
                "DEVICE_PATH",
                os.path.join(self._tmp.name, ".device"),
            ),
            # the API keys and the request
            mock.patch.object(
                prices, "_headers", lambda: {}
            ),
            mock.patch.object(
                prices,
                "_latest_prices",
                self._fake_latest,
            ),
            mock.patch.object(
                prices, "_bars", self._fake_bars
            ),
            # Telegram, whatever config.json "notify"
            # is, set up but never called
            mock.patch.object(
                notifier, "channel", telegram_notify
            ),
            mock.patch.object(notifier, "NAME", "telegram"),
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
                alerts, "start", self._fake_alerts_start
            ),
            mock.patch.object(
                alerts, "stop", self._fake_alerts_stop
            ),
            mock.patch.object(
                alerts,
                "running_pid",
                lambda: (
                    FAKE_PID
                    if self.alerts_running
                    else None
                ),
            ),
            mock.patch.object(
                subprocess, "run", self._fake_run
            ),
        ]
        for p in self._patches:
            p.start()
        # the tables are pinned at the default width,
        # and theme, whatever config.json says
        # (test_width and test_theme change them), and
        # the averages have no trade fee
        config_patch = mock.patch.dict(config.DATA)
        config_patch.start()
        self._patches.append(config_patch)
        config.DATA.pop("terminal", None)
        config.DATA.pop("fee", None)
        self.shell = NxSigShell()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        storage.DB_DIR = self._db_dir
        self._tmp.cleanup()

    # ---------------- fakes ----------------

    def _fake_start(self, ladder_id, force=False):
        self.forced.append(force)
        if storage.ladder_get(ladder_id) is None:
            raise ladder.LadderError(
                f"no ladder {ladder_id}, see 'ls ladders'"
            )
        self.running.add(ladder_id)
        return FAKE_PID

    def _fake_latest(self, headers, feed=None):
        self.feeds.append(feed)
        return dict(self.prices)

    def _fake_bars(self, headers, symbol, days, timeframe):
        self.bars_calls.append((symbol, days, timeframe))
        if isinstance(self.bars, Exception):
            raise self.bars
        return list(self.bars)

    def _fake_alerts_start(self, force=False):
        self.alerts_forced.append(force)
        # the real checks before the process starts
        if not alerts.alerts_get_all():
            raise alerts.AlertError(
                "no alerts, see 'help add alert'"
            )
        if self.alerts_running:
            raise alerts.AlertError(
                "the alerts are already checked (pid "
                f"{FAKE_PID})"
            )
        try:
            tasks_owner.claim(force)
        except tasks_owner.OwnerError as e:
            raise alerts.AlertError(str(e)) from None
        self.alerts_running = True
        return FAKE_PID

    def _fake_alerts_stop(self):
        was_running = self.alerts_running
        self.alerts_running = False
        return was_running

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
                width(),
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
            trades.total(storage.Stock.SOXL),
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

    def write_statement(self, text):
        path = os.path.join(self._tmp.name, "bank.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_add_trade_from_statement(self):
        path = self.write_statement(
            '"22/10/26, 19:46","22/10/26, 19:46","x",'
            '"y","Պատվեր թիվ 699534, 2026/10/22, 10.00'
            ' հատ AVGG առք","-182.19 USD","-182.19 USD"\n'
            '"22/10/26, 19:46","22/10/26, 19:46","x",'
            '"y","Միջնորդավճար / Պատվեր թիվ 699534,'
            ' 2026/10/22, 10.00 հատ AVGG առք",'
            '"-5.00 USD","-5.00 USD"\n'
            '"10/12/25, 23:34","10/12/25, 23:34","x",'
            '"y","Պատվեր թիվ 460827, 2025/12/10, 14.00'
            ' հատ VOO վաճառք","+8,834.00 USD",'
            '"+8,834.00 USD"\n'
        )
        self.assertEqual(
            self.lines(f"add trade from {path}"),
            [
                "added 1 trades from bank.csv:",
                "  AVGG BUY 10 @ 18.219, 22.10.26 19:46",
                "skipped 1:",
                "  order 460827: no stock VOO",
            ],
        )
        self.assertEqual(
            len(storage.trades_get_all(storage.Stock.AVGG)),
            1,
        )
        self.assertEqual(
            self.lines(f"add trade FROM {path}"),
            [
                "no trades added from bank.csv",
                "skipped 2:",
                "  order 460827: no stock VOO",
                "  order 699534: already recorded",
            ],
        )

    def test_add_trade_from_bad_file(self):
        self.assertEqual(
            self.lines("add trade from"),
            ["usage: add trade from <file>"],
        )
        missing = os.path.join(self._tmp.name, "no.csv")
        self.assertIn(
            "error: No such file or directory",
            self.run_cmd(f"add trade from {missing}"),
        )
        path = os.path.join(self._tmp.name, "bin.csv")
        with open(path, "wb") as f:
            f.write(b"\xff\xfe\xfa")
        self.assertIn(
            "error: not a text file",
            self.run_cmd(f"add trade from {path}"),
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
        self.assertEqual(out[1], "-" * width())
        self.assertRegex(
            out[2],
            r"^   1 \| \d\d\.\d\d\.\d\d \| \d\d:\d\d \|"
            r"  BUY \|    10 \| 20.00$",
        )
        self.assertRegex(out[3], r"^   2 \| .* 30.00$")
        self.assertEqual(out[4], "-" * width())
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
            ["Name  | Trades | Last trade", "-" * 31],
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
            trades.total(storage.Stock.SOXL),
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
                "-" * 47,
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
            prices, "_headers", missing_key
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
            ["no stocks held", "mail broker: not started"],
        )
        self.run_cmd("add trade SOXL buy count 10 price 20")
        self.prices = {"SOXL": 22}
        self.assertEqual(
            self.lines("status"),
            [
                "Name  | Count | Avg Price |    Price | "
                "    State",
                "-" * width(),
                "SOXL  |    10 |     20.00 |    22.00 | "
                "   +20.00",
                "-" * width(),
                "mail broker: not started",
            ],
        )
        self.assertEqual(
            self.lines("status now"), ["usage: status"]
        )

    def test_status_mail_broker(self):
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
                f"mail broker: running, checked "
                f"{now:%H:%M}, last order",
                "  BUY 10 SOXL",
            ],
        )

    def test_xtop_checks(self):
        self.assertEqual(
            self.lines("xtop 1 2"),
            ["usage: xtop [sec] [al]"],
        )
        self.assertEqual(
            self.lines("xtop al al"),
            ["usage: xtop [sec] [al]"],
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
                "-" * 47,
                "MUU      2    50.00        -         -"
                "        -",
                "SOXL    10    20.00    22.00    +20.00"
                "  +10.00%",
                "-" * 47,
                "total                           +20.00"
                "  +10.00%",
                "updated 09:30:05, every 5s, q to stop",
                "a note",
            ],
        )

    def run_xtop(self, line):
        """line's xtop output: one price update, then q"""
        keys = iter([None, "q"])

        def polling(interval, on_update, on_error):
            on_update(self.prices)
            return threading.Event()

        @contextmanager
        def reader():
            yield lambda: next(keys)

        with mock.patch.object(
            shell.overview_cmd, "start_polling", polling
        ), mock.patch.object(
            shell.overview_cmd, "key_reader", reader
        ):
            return self.lines(line)

    def test_xtop_run(self):
        self.run_cmd("add trade SOXL buy count 10 price 20")
        self.run_cmd("add alert gain SOXL 20")
        self.prices = {"SOXL": 22}
        # the gain alerts only with al; q stops it
        out = self.run_xtop("xtop")
        self.assertTrue(out[-1].endswith("q to stop"))
        self.assertNotIn("alert 1 gain SOXL +20", out)
        out = self.run_xtop("xtop 10 al")
        self.assertIn("alert 1 gain SOXL +20", out)
        self.assertIn("! in alert: SOXL #1", out)
        self.assertIn("every 10s", " ".join(out))
        out = self.run_xtop("xtop al 10")
        self.assertIn("alert 1 gain SOXL +20", out)
        # not a terminal: no key is read
        with mock.patch.object(
            shell.ui.sys.stdin, "isatty", lambda: False
        ), shell.ui.key_reader() as read:
            self.assertIsNone(read())

    def test_xtop_gain_alerts(self):
        self.run_cmd("add trade SOXL buy count 10 price 20")
        self.run_cmd("add trade MUU buy count 2 price 50")
        prices = {"SOXL": 22, "MUU": 49}
        self.assertEqual(
            gain_alert_lines(prices),
            ["no gain alerts, see 'help add alert'"],
        )
        self.run_cmd("add alert gain SOXL 20")
        self.run_cmd("add alert gain all -1 percent")
        # SOXL: 20 + 20 / 10 = 22, reached; MUU: 50 - 1%
        lines = _xtop_lines(
            prices,
            None,
            None,
            5,
            False,
            gain_alert_lines(prices),
        )
        self.assertEqual(
            lines[-4:],
            [
                "alert 1 gain SOXL +20",
                "alert 2 gain all -1%",
                "! in alert: SOXL #1, MUU #2",
                "alerts: running",
            ],
        )
        # a gain alert for a stock not held
        self.run_cmd("add alert gain TSMX 10")
        self.assertIn(
            "alert 3 gain TSMX +10",
            gain_alert_lines(prices),
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
                "-" * width(),
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
                "-" * width(),
                "MUU        2       50.50           -"
                "           -",
                "SOXL       5       18.00       19.80"
                "     +10.00%",
            ],
        )
        self.assertEqual(
            self.lines("ls basetrades al")[4:],
            ["no basetrade alerts, see 'help add alert'"],
        )

    def test_basetrades_feed(self):
        self.lines("add basetrade SOXL price 18 count 5")
        self.prices = {"SOXL": 19.8}
        table = self.lines("ls basetrades")
        self.assertEqual(self.feeds, [None])
        # sip is the delayed one, in either order with al
        for line, feed in (
            ("ls basetrades sip", "delayed_sip"),
            ("ls basetrades IEX", "iex"),
            ("ls basetrades sip al", "delayed_sip"),
            ("ls basetrades al iex", "iex"),
        ):
            self.feeds = []
            out = self.lines(line)
            self.assertEqual(out[:3], table, line)
            self.assertEqual(self.feeds, [feed], line)
        for line in (
            "ls basetrades sip iex",
            "ls basetrades al al",
            "ls basetrades delayed_sip",
        ):
            self.assertEqual(
                self.lines(line),
                ["usage: ls basetrades [sip|iex] [al]"],
                line,
            )

    def test_latest_prices_feed(self):
        calls = []

        def fake_get(url, params, headers, timeout):
            calls.append(dict(params))
            response = mock.Mock()
            response.json.return_value = {
                "trades": {"SOXL": {"p": 19.8}}
            }
            return response

        with mock.patch.object(
            prices.requests, "get", fake_get
        ), mock.patch.dict(config.DATA, {"feed": "iex"}):
            self.assertEqual(REAL_LATEST({})["SOXL"], 19.8)
            REAL_LATEST({}, "delayed_sip")
        self.assertEqual(
            [c["feed"] for c in calls],
            ["iex", "delayed_sip"],
        )

    def test_basetrade_errors(self):
        usage = [
            "usage: add basetrade <stock>|all, or add",
            "  basetrade <stock> price <price> count "
            "<count>",
        ]
        for line in (
            "add basetrade SOXL price 20",
            "add basetrade SOXL price 20 qty 10",
            "add basetrade SOXL price 20 price 10",
            "add basetrade",
            "add basetrade SOXL price",
            "add basetrade all SOXL",
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
            ["usage: ls basetrades [sip|iex] [al]"],
        )

    def _lowest_trades(self):
        # SOXL: the lowest buy 3 at 15 on 02.10;
        # MUU: sold after its buy
        found = [
            ("SOXL", TradeType.BUY, 5, 20),
            ("SOXL", TradeType.BUY, 3, 15),
            ("SOXL", TradeType.BUY, 2, 19),
            ("MUU", TradeType.BUY, 4, 50),
            ("MUU", TradeType.SELL, 1, 55),
        ]
        for day, (name, kind, count, price) in enumerate(
            found, 1
        ):
            trades.add(
                Stock[name],
                kind,
                count,
                price,
                f"{day:02}.10.2026",
                "10:00",
            )

    def test_add_basetrade_from_trades(self):
        self._lowest_trades()
        self.assertEqual(
            self.lines("add basetrade soxl"),
            [
                "added basetrade of SOXL: 3 at 15 (lowest "
                "buy",
                "  since the last sell, 02.10.26)",
            ],
        )
        self.assertEqual(
            self.lines("add basetrade SOXL"),
            [
                "replaced basetrade of SOXL: 3 at 15 "
                "(lowest buy",
                "  since the last sell, 02.10.26)",
            ],
        )
        self.assertEqual(
            self.lines("add basetrade MUU"),
            [
                "error: no buys of MUU since the last "
                "sell, see",
                "  'ls trades'",
            ],
        )
        self.assertEqual(
            self.lines("add basetrade MRVU"),
            ["error: no buys of MRVU, see 'ls trades'"],
        )

    def test_add_basetrade_all(self):
        self.assertEqual(
            self.lines("add basetrade all"),
            [
                "error: no stock has a lowest buy since "
                "the last",
                "  sell, see 'ls trades'",
            ],
        )
        self._lowest_trades()
        added = [
            "from the lowest buy since the last sell:",
            "skipped MUU: no buys since the last sell",
            "added SOXL: 3 at 15 (02.10.26)",
        ]
        # no older basetrade, no question
        self.assertEqual(
            self.lines("add basetrade all"), added
        )
        self.run_cmd("add basetrade SOXL price 9 count 1")
        question = [
            "this replaces the basetrades of SOXL",
            "go on? [y/N] n",
            "cancelled",
        ]
        self.assertEqual(
            self.lines("add basetrade ALL", "n"), question
        )
        self.assertEqual(
            basetrades.get("SOXL")["Price"], 9.0
        )
        self.assertEqual(
            self.lines("add basetrade all", "y"),
            [
                "this replaces the basetrades of SOXL",
                "go on? [y/N] y",
                *added[:2],
                "replaced SOXL: 3 at 15 (02.10.26)",
            ],
        )
        self.assertEqual(basetrades.get("SOXL")["Count"], 3)
        self.assertIsNone(basetrades.get("MUU"))

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

    # ---------------- alerts ----------------

    def test_alerts(self):
        self.assertEqual(
            self.lines("ls alerts"),
            ["no alerts yet, see 'help add alert'"],
        )
        # the first alert starts the alerts process
        self.assertEqual(
            self.lines(
                "add alert basetrades down 10 percent"
            ),
            [
                "alert 1 saved: basetrades down 10%",
                f"alerts started (pid {FAKE_PID})",
            ],
        )
        self.assertEqual(
            self.lines("add alert BASETRADES up 20 %"),
            ["alert 2 saved: basetrades up 20%"],
        )
        self.assertEqual(self.alerts_forced, [False])
        created = [
            a["Created"] for a in alerts.alerts_get_all()
        ]
        self.assertEqual(
            self.lines("ls alerts"),
            [
                "Id  For         Alert         Created",
                "-" * 46,
                " 1  basetrades  down 10%      "
                f"{created[0]}",
                " 2  basetrades  up 20%        "
                f"{created[1]}",
                "alerts: running",
            ],
        )
        self.assertEqual(
            self.lines("ls alerts all"),
            ["usage: ls alerts"],
        )

    def test_basetrades_with_alerts(self):
        self.run_cmd("add basetrade SOXL price 20 count 10")
        self.run_cmd("add basetrade MUU price 50.5 count 2")
        self.run_cmd("add alert basetrades down 10 percent")
        self.run_cmd("add alert basetrades up 20 percent")
        self.prices = {"SOXL": 17.9, "MUU": 61}
        now = datetime.now()
        storage.alerts_status_set(
            {"pid": FAKE_PID, "updated": now.isoformat()}
        )
        # the alerts only with al
        self.assertEqual(
            len(self.lines("ls basetrades")), 4
        )
        # a ! marks the levels the price is past
        self.assertEqual(
            self.lines("ls basetrades al")[4:],
            [
                "alert 1 down 10%: MUU 45.45, SOXL 18.00!",
                "alert 2 up 20%: MUU 60.60!, SOXL 24.00",
                "! in alert: SOXL #1, MUU #2",
                f"alerts: running, last check {now:%H:%M}",
            ],
        )
        self.prices = {"SOXL": 19}
        self.run_cmd("stop alerts")
        self.assertEqual(
            self.lines("ls basetrades al")[4:],
            [
                "alert 1 down 10%: MUU 45.45, SOXL 18.00",
                "alert 2 up 20%: MUU 60.60, SOXL 24.00",
                "alerts: not running, see 'run alerts'",
            ],
        )
        storage.tasks_owner_set(OTHER_OWNER)
        self.assertEqual(
            self.lines("ls basetrades al")[-2:],
            [
                "alerts: not running here, the background "
                "tasks",
                "  run on pc (since 16.10 14:30)",
            ],
        )

    def test_basetrade_alerts_wrap(self):
        # all seven stocks: the next lines start under
        # the first stock, a stock and its price stay
        # together
        for name, price in (
            ("ASMG", 40.94),
            ("AVGG", 21.7),
            ("NVDL", 31.84),
            ("TSMX", 71.7),
            ("MUU", 24.2),
            ("MRVU", 112.59),
            ("SOXL", 100.64),
        ):
            self.run_cmd(
                f"add basetrade {name} price {price} "
                "count 1"
            )
        self.run_cmd("add alert basetrades down 10 percent")
        self.prices = {
            "AVGG": 19,
            "MUU": 20,
            "SOXL": 80,
            "TSMX": 60,
        }
        out = self.lines("ls basetrades al")
        indent = " " * len("alert 1 down 10%: ")
        first = out.index(
            "alert 1 down 10%: ASMG 36.85, AVGG 19.53!,"
        )
        self.assertEqual(
            out[first:],
            [
                "alert 1 down 10%: ASMG 36.85, "
                "AVGG 19.53!,",
                indent + "NVDL 28.66, TSMX 64.53!,",
                indent + "MUU 21.78!, MRVU 101.33,",
                indent + "SOXL 90.58!",
                "! in alert: AVGG #1, TSMX #1, MUU #1, "
                "SOXL #1",
                "alerts: running",
            ],
        )
        # in color the ! is red, the line stays dimmed
        with mock.patch.object(
            shell.ui, "supports_color", lambda: True
        ), mock.patch.object(
            shell.alert_cmd, "supports_color", lambda: True
        ):
            # run_cmd's width check would count the
            # color codes
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                self.shell.onecmd("ls basetrades al")
            out = buffer.getvalue()
        self.assertIn(
            "\033[2m! in alert: AVGG #1",
            out.replace("\033[38;5;124m!\033[39m", "!"),
        )
        self.assertIn(
            "AVGG 19.53\033[38;5;124m!\033[39m,", out
        )

    def test_gain_alerts(self):
        self.assertEqual(
            self.lines("add alert gain tsmx 100"),
            [
                "alert 1 saved: gain TSMX +100",
                f"alerts started (pid {FAKE_PID})",
            ],
        )
        for line, saved in (
            ("add alert gain all 10 percent", "all +10%"),
            ("add alert gain ALL -5%", "all -5%"),
            ("add alert gain SOXL -50.5", "SOXL -50.5"),
        ):
            self.assertEqual(
                self.lines(line)[0].split(": ")[1],
                f"gain {saved}",
                line,
            )
        rows = self.lines("ls alerts")[2:6]
        self.assertEqual(
            [r[:28].rstrip() for r in rows],
            [
                " 1  gain        TSMX +100",
                " 2  gain        all +10%",
                " 3  gain        all -5%",
                " 4  gain        SOXL -50.5",
            ],
        )
        self.assertEqual(
            self.lines("rm alert 1", "y")[0],
            "delete alert 1: gain TSMX +100? [y/N] y",
        )
        usage = self.lines("add alert gain")
        self.assertEqual(usage[0][:6], "usage:")
        for line in (
            "add alert gain TSMX",
            "add alert gain TSMX 1 2",
            "add alert gain TSMX 1 times",
        ):
            self.assertEqual(self.lines(line), usage, line)
        for line, error in (
            (
                "add alert gain XXX 100",
                "error: unknown stock 'XXX'",
            ),
            (
                "add alert gain TSMX x",
                "error: <n> must be a number",
            ),
            (
                "add alert gain TSMX 0",
                "error: the gain can't be 0",
            ),
            (
                "add alert gain all -100 percent",
                "error: a loss can't be 100 percent or "
                "more",
            ),
        ):
            self.assertEqual(
                self.lines(line), [error], line
            )

    def test_alert_errors(self):
        usage = [
            "usage: add alert basetrades <down|up> <n>",
            "  percent, or add alert gain <stock|all> <n>",
            "  [percent]",
        ]
        for line in (
            "add alert",
            "add alert basetrades down 10",
            "add alert basetrades down 10 times",
        ):
            self.assertEqual(self.lines(line), usage, line)
        for line, error in (
            (
                "add alert stocks down 10 percent",
                ["error: alerts are for basetrades/gain"],
            ),
            (
                "add alert basetrades left 10 percent",
                [
                    "error: unknown direction 'left', "
                    "expected",
                    "  down/up",
                ],
            ),
            (
                "add alert basetrades down x percent",
                ["error: <n> must be a number"],
            ),
            (
                "add alert basetrades down 100 percent",
                [
                    "error: a price can't go down 100 "
                    "percent or more"
                ],
            ),
            (
                "add alert basetrades up 0 percent",
                ["error: percent must be positive"],
            ),
        ):
            self.assertEqual(self.lines(line), error, line)
        with mock.patch.dict(os.environ, {"TOKEN": ""}):
            self.assertEqual(
                self.lines(
                    "add alert basetrades down 5 percent"
                ),
                [
                    "error: Telegram isn't set up, add "
                    "TOKEN and",
                    "  CHAT_ID to .env",
                ],
            )
        self.assertEqual(alerts.alerts_get_all(), [])
        self.assertFalse(self.alerts_running)

    def test_rm_alert(self):
        self.run_cmd("add alert basetrades down 10 percent")
        self.run_cmd("add alert basetrades up 20 percent")
        self.assertEqual(
            self.lines("rm alert 1", "n"),
            [
                "delete alert 1: basetrades down 10%? "
                "[y/N] n",
                "cancelled",
            ],
        )
        self.assertEqual(
            self.lines("rm alert 1", "y")[-1],
            "deleted alert 1",
        )
        self.assertTrue(self.alerts_running)
        # the last one stops the alerts process
        self.assertEqual(
            self.lines("rm alert 2", "y")[-1],
            "deleted alert 2, no alerts left: alerts "
            "stopped",
        )
        self.assertFalse(self.alerts_running)
        self.assertEqual(
            self.lines("rm alert 2"),
            ["error: no alert 2, see 'ls alerts'"],
        )
        for line in (
            "rm alert",
            "rm alert x",
            "rm alert 1 2",
        ):
            self.assertEqual(
                self.lines(line),
                ["usage: rm alert <id>"],
                line,
            )

    def test_run_and_stop_alert(self):
        self.assertEqual(
            self.lines("run alerts"),
            ["error: no alerts, see 'help add alert'"],
        )
        self.assertEqual(
            self.lines("stop alerts"),
            ["the alerts aren't running"],
        )
        # saved, but another device runs the tasks
        storage.tasks_owner_set(OTHER_OWNER)
        self.assertEqual(
            self.lines(
                "add alert basetrades down 10 percent"
            ),
            [
                "alert 1 saved: basetrades down 10%",
                "error: pc (since 16.10 14:30) runs the",
                "  background tasks: stop them there, or "
                "add",
                "  'force' if it is off",
            ],
        )
        self.assertEqual(
            self.lines("run alerts force"),
            [
                "taking over the background tasks from pc "
                "(since",
                "  16.10 14:30)",
                f"alerts started (pid {FAKE_PID})",
            ],
        )
        self.assertEqual(
            self.lines("run alerts"),
            [
                "error: the alerts are already checked "
                f"(pid {FAKE_PID})"
            ],
        )
        self.assertEqual(
            self.lines("stop alerts"), ["alerts stopped"]
        )
        # plural, one process runs every alert
        self.assertEqual(
            self.lines("run alert"), ["use 'run alerts'"]
        )
        self.assertEqual(
            self.lines("stop alert"),
            ["use 'stop alerts'"],
        )
        for line, usage in (
            ("run alerts x", "usage: run alerts [force]"),
            ("stop alerts 1", "usage: stop alerts"),
        ):
            self.assertEqual(self.lines(line), [usage])

    def test_alerts_task(self):
        self.run_cmd("add alert basetrades down 10 percent")
        now = datetime.now()
        storage.alerts_status_set(
            {
                "pid": FAKE_PID,
                "started": now.isoformat(),
                "updated": now.isoformat(),
                "state": "waiting",
            }
        )
        self.assertEqual(
            self.lines("ls tasks")[2],
            f" -  alerts          {FAKE_PID}  "
            f"{now:%d.%m %H:%M}  waiting",
        )
        storage.alerts_status_set(
            {
                "pid": FAKE_PID,
                "updated": (
                    now - timedelta(hours=1)
                ).isoformat(),
                "state": "waiting",
            }
        )
        self.assertEqual(
            self.lines("ls tasks")[2],
            f" -  alerts          {FAKE_PID}  -"
            "            no reply",
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
        with mock.patch.object(
            notifier, "channel", termux_notify
        ), mock.patch.object(
            termux_notify.shutil, "which", lambda n: None
        ):
            self.assertEqual(
                self.lines("add ladder SOXL up 5 from 100"),
                [
                    "error: Termux:API isn't set up, "
                    "install the",
                    "  Termux:API app and run 'pkg install",
                    "  termux-api'",
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
        for line in (
            "run ladder",
            "run ladder SOXL down",
            "run ladder 1 now",
        ):
            self.assertEqual(
                self.lines(line),
                ["usage: run ladder <id> [force]"],
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

    def test_run_ladder_force(self):
        self.run_cmd("add ladder SOXL down 10 from 100")
        storage.tasks_owner_set(OTHER_OWNER)
        self.assertEqual(
            self.lines("run ladder 1 force"),
            [
                "taking over the background tasks from "
                "pc (since",
                "  16.10 14:30)",
                "starting ladder 1...",
                f"ladder 1 started (pid {FAKE_PID}), next "
                "alert at 90",
            ],
        )
        self.run_cmd("stop ladder 1")
        # this device owns them: no take-over line
        tasks_owner.claim(force=True)
        self.assertEqual(
            self.lines("run ladder 1 FORCE")[0],
            "starting ladder 1...",
        )
        self.assertEqual(self.forced, [True, True])

    def test_ls_ladders(self):
        self.assertEqual(
            self.lines("ls ladders"),
            ["no ladders yet, see 'help add ladder'"],
        )
        self.run_cmd("add ladder SOXL down 10 from 100 run")
        self.run_cmd("add ladder MRVU up 2.5 from 40")
        header = [
            "Id  Stock  Ladder        From     Next  State",
            "-" * 47,
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
        self.run_cmd("run mail-broker force")
        self.assertEqual(
            self.mtsig_calls,
            [
                [mtsig, "start"],
                [mtsig, "stop"],
                [mtsig, "start", "force"],
            ],
        )
        self.assertEqual(
            self.lines("run mail-broker now"),
            ["usage: run mail-broker [force]"],
        )
        self.assertEqual(
            self.lines("stop mail-broker now"),
            ["usage: stop mail-broker"],
        )

    # ---------------- the demo ----------------

    def demo(self):
        """the shell as ./nxdemo starts it, its prices
        process runs"""
        for target, name, value in (
            (config, "DEMO", True),
            (demo_prices, "running_pid", lambda: 77),
        ):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.shell.set_prompt()

    def test_demo_prompt(self):
        self.assertEqual(self.shell.prompt, "nX-sig> ")
        self.demo()
        self.assertEqual(self.shell.prompt, "nX-sig demo> ")

    def test_demo_status(self):
        self.demo()
        self.assertEqual(
            self.lines("status"),
            [
                "no stocks held",
                "mail broker: not in the demo",
                "demo: made-up prices, moving every 2s "
                "(pid 77)",
            ],
        )

    def test_demo_mail_broker(self):
        self.demo()
        refused = [
            "the mail broker is not in the demo, it "
            "records",
            "  real broker emails",
        ]
        self.assertEqual(
            self.lines("run mail-broker"), refused
        )
        self.assertEqual(
            self.lines("stop mail-broker"), refused
        )
        self.assertEqual(self.mtsig_calls, [])

    def test_demo_messages(self):
        def after_command():
            out = io.StringIO()
            with redirect_stdout(out):
                self.shell.postcmd(False, "status")
            return out.getvalue().splitlines()

        demo.message_add("SOXL up")
        # outside the demo nothing is printed
        self.assertEqual(after_command(), [])
        self.demo()
        found = after_command()
        self.assertEqual(len(found), 1)
        self.assertRegex(
            found[0], r"^\[DEMO\] \d\d:\d\d:\d\d SOXL up$"
        )
        self.assertEqual(after_command(), [])

    def test_demo_messages_colored(self):
        # the color codes don't count when wrapping
        self.demo()
        text = "SOXL down to 33.26, passed 34 (ladder 1)"
        demo.message_add(text)
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(
            shell.demo_cmd, "supports_color", lambda: True
        ):
            self.shell.postcmd(False, "")
        lines = [
            re.sub(r"\x1b\[[0-9;]*m", "", l)
            for l in out.getvalue().splitlines()
        ]
        # as wrapped without colors
        clock = lines[0].split()[1]
        self.assertEqual(
            "\n".join(lines),
            shell.ui.wrap(f"[DEMO] {clock} {text}"),
        )
        self.assertEqual(len(lines), 2)

    def test_demo_outside(self):
        self.assertEqual(
            self.lines("demo tour"),
            ["only in the demo, start it with ./nxdemo"],
        )

    def test_demo_usage(self):
        self.demo()
        for line in ("demo", "demo fly"):
            self.assertTrue(
                self.lines(line)[0].startswith(
                    "usage: demo set"
                ),
                line,
            )
        for line, usage in (
            ("demo set SOXL", "set <stock> <price>"),
            ("demo move SOXL 5", "move <stock|all> <n>%"),
            ("demo speed 1 2", "speed [<n>]"),
            ("demo reset now", "reset"),
            ("demo tour now", "tour"),
        ):
            self.assertEqual(
                self.lines(line), [f"usage: demo {usage}"]
            )

    def test_demo_set_move(self):
        self.demo()
        demo_prices.create()
        self.assertEqual(
            self.lines("demo set soxl 30"),
            ["SOXL: 50.00 -> 30.00"],
        )
        self.assertEqual(
            self.lines("demo move SOXL -10%"),
            ["SOXL: 30.00 -> 27.00"],
        )
        moved = self.lines("demo move all +10%")
        self.assertEqual(len(moved), len(config.indices()))
        self.assertIn("SOXL: 27.00 -> 29.70", moved)
        self.assertEqual(
            self.lines("demo set SOXL x"),
            ["error: the price must be a number, not 'x'"],
        )
        self.assertEqual(
            self.lines("demo set SOXL 0"),
            ["error: the price must be above 0"],
        )
        self.assertEqual(
            self.lines("demo move SOXL -95%"),
            ["error: the change must be -90% to +1000%"],
        )
        self.assertTrue(
            self.lines("demo set XX 1")[0].startswith(
                "error: unknown stock 'XX'"
            )
        )
        self.assertEqual(demo_prices.latest()["SOXL"], 29.7)

    def test_demo_speed(self):
        self.demo()
        demo_prices.create()
        self.assertEqual(
            self.lines("demo speed"),
            ["speed: 300 times real time, a move every 2s"],
        )
        self.assertEqual(
            self.lines("demo speed 20"),
            ["speed: 20 times real time, a move every 2s"],
        )
        self.assertEqual(
            self.lines("demo speed 0"),
            ["error: the speed must be 1 to 10000"],
        )
        self.assertEqual(demo_prices.speed(), 20)

    def test_demo_reset(self):
        self.demo()
        demo.prepare()
        self.running.add(1)
        self.alerts_running = True
        self.run_cmd("add rule my rule")
        self.assertEqual(
            self.lines("demo reset", answer="n")[-1],
            "not reset",
        )
        self.assertEqual(self.running, {1})
        found = self.lines("demo reset", answer="y")
        self.assertEqual(found[2], "start over? [y/N] y")
        self.assertEqual(
            " ".join(l.strip() for l in found[3:]),
            "the demo starts over: sample data, new "
            "prices; 2 tasks stopped",
        )
        self.assertEqual(self.running, set())
        self.assertFalse(self.alerts_running)
        self.assertNotIn(
            "my rule", self.run_cmd("ls rules")
        )

    def test_demo_tour(self):
        self.demo()
        found = self.lines("demo tour")
        self.assertEqual(
            found[0], "things to try, in this order:"
        )
        self.assertTrue(
            found[1].startswith(" 1. ls stocks")
        )

    def test_demo_complete(self):
        self.assertEqual(
            self.complete("demo s"), ["set", "speed"]
        )
        self.assertIn("all", self.complete("demo move "))
        self.assertNotIn("all", self.complete("demo set "))
        self.assertIn("SOXL", self.complete("demo set "))
        self.assertEqual(self.complete("demo tour "), [])

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
            process, "process_runs", lambda *a: True
        ):
            out = self.lines("ls tasks")
        self.assertEqual(
            out,
            [
                "Id  Task             PID  Started      "
                "State",
                "-" * width(),
                f" 1  ladder SOXL     {FAKE_PID}  "
                f"{started}  waiting",
                f" -  mail-broker      777  {started}  "
                "connected",
            ],
        )
        self.assertEqual(
            self.lines("ls tasks -a"), ["usage: ls tasks"]
        )

    def test_stop_tasks_all(self):
        self.assertEqual(
            self.lines("stop tasks all"),
            ["no background tasks running"],
        )
        self.run_cmd("add ladder SOXL down 10 from 100 run")
        self.run_cmd("add ladder MUU up 5 from 50 run")
        self.run_cmd("add alert basetrades down 10 percent")
        with open(
            os.path.join(storage.DB_DIR, "mtsig.pid"), "w"
        ) as f:
            f.write("777\n")
        with mock.patch.object(
            process, "process_runs", lambda *a: True
        ):
            out = self.lines("stop tasks all")
        self.assertEqual(
            out,
            [
                "ladder 1 stopped",
                "ladder 2 stopped",
                "alerts stopped",
                "stopping the mail broker...",
                "mtsig stop: ok",
            ],
        )
        self.assertEqual(self.running, set())
        self.assertFalse(self.alerts_running)
        self.assertEqual(self.mtsig_calls[-1][-1], "stop")
        for line in ("stop tasks", "stop tasks 1"):
            self.assertEqual(
                self.lines(line),
                ["usage: stop tasks all"],
                line,
            )
        # plural, like ls
        self.assertEqual(
            self.lines("stop task all"),
            ["use 'stop tasks all'"],
        )
        self.assertEqual(
            self.complete("stop tasks "), ["all"]
        )

    def test_tasks_owner(self):
        storage.tasks_owner_set(OTHER_OWNER)
        self.assertEqual(
            self.lines("ls tasks"),
            [
                "no background tasks running",
                "background tasks run on pc (since 16.10 "
                "14:30)",
            ],
        )
        self.assertEqual(
            self.lines("status"),
            [
                "no stocks held",
                "mail broker: not started",
                "background tasks run on pc (since 16.10 "
                "14:30)",
            ],
        )
        tasks_owner.claim(force=True)
        name = tasks_owner.this_device()["name"]
        self.assertEqual(
            self.lines("ls tasks")[-1],
            f"background tasks run here ({name})",
        )
        tasks_owner.release()
        self.assertEqual(
            self.lines("ls tasks"),
            ["no background tasks running"],
        )

    # ---------------- the action commands ----------------

    def test_bare_action_lists_objects(self):
        self.assertEqual(
            self.lines("ls"),
            [
                "ls: stocks, trades, ladders, rules, "
                "basetrades,",
                "  alerts, tasks",
            ],
        )
        self.assertEqual(
            self.lines("add"),
            ["add: trade, ladder, rule, basetrade, alert"],
        )
        self.assertEqual(
            self.lines("rm"),
            ["rm: trade, ladder, rule, basetrade, alert"],
        )
        self.assertEqual(
            self.lines("run"),
            ["run: ladder, alerts, mail-broker"],
        )
        self.assertEqual(
            self.lines("stop"),
            ["stop: ladder, alerts, mail-broker, tasks"],
        )

    def test_action_errors(self):
        self.assertEqual(
            self.lines("rm x 1"),
            [
                "unknown object 'x' for rm, expected",
                "  trade/ladder/rule/basetrade/alert",
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
                "add trade from <file>",
                "    record the trades of a bank statement",
                "    csv; fees, stocks not in the config"
                " and",
                "    trades already recorded are left out",
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
        # every command has a help text that fits width()
        for name in self.shell.get_names():
            if name.startswith("do_") and name != "do_EOF":
                self.assertTrue(
                    self.run_cmd(
                        f"help {name[3:]}"
                    ).strip(),
                    name,
                )

    # ---------------- the width ----------------

    def test_width_setting(self):
        from shell import ui

        self.assertEqual(width(), 48)
        self.assertEqual(ui.setting_problems(), [])
        with mock.patch.dict(
            config.DATA, {"terminal": {"width": 60}}
        ):
            self.assertEqual(width(), 60)
            # .env has no say
            with mock.patch.dict(
                os.environ, {"NX_WIDTH": "100"}
            ):
                self.assertEqual(width(), 60)
        auto = mock.patch.dict(
            config.DATA, {"terminal": {"width": "auto"}}
        )
        with auto, mock.patch.dict(
            os.environ, {"COLUMNS": "90"}
        ):
            self.assertEqual(width(), 90)
            self.assertEqual(ui.setting_problems(), [])
        with auto, mock.patch.dict(
            os.environ, {"COLUMNS": "40"}
        ):
            self.assertEqual(width(), 48)
            self.assertEqual(
                ui.setting_problems(),
                ["the terminal is 40 wide, using 48"],
            )
        with mock.patch.dict(
            config.DATA, {"terminal": {"width": 30}}
        ):
            self.assertEqual(width(), 48)
            self.assertEqual(
                ui.setting_problems(),
                ["width 30 is too narrow, using 48"],
            )
            self.assertIn(
                "width 30 is too narrow",
                NxSigShell().intro,
            )
        with mock.patch.dict(
            config.DATA, {"terminal": {"width": "wide"}}
        ):
            self.assertEqual(width(), 48)
            self.assertEqual(
                ui.setting_problems(),
                [
                    "width 'wide' is not a number or auto, "
                    "using 48"
                ],
            )

    def test_wide_screen(self):
        self.prices = {"SOXL": 25.5}
        self.run_cmd(
            "add trade SOXL buy count 10 price 20.5"
        )
        self.run_cmd("add ladder SOXL down 10 from 100")
        with mock.patch.dict(
            config.DATA, {"terminal": {"width": 80}}
        ):
            # run_cmd checks that every line fits 80
            status = self.lines("status")
            self.assertEqual(
                status[:3],
                [
                    "Name    |   Count   |   Avg Price   |"
                    "      Price   |       State",
                    # as wide as the columns, not 80
                    "-" * 64,
                    "SOXL    |      10   |       20.50   |"
                    "      25.50   |      +50.00",
                ],
            )
            # the gaps grow by at most 4
            self.assertEqual(
                self.lines("ls ladders")[0],
                "Id      Stock      Ladder            From"
                "         Next      State",
            )
            # the help fills the width
            self.assertEqual(
                self.lines("help stop ladder"),
                [
                    "stop ladder <id>",
                    "    stop a running ladder, it stays "
                    "saved",
                ],
            )
            # the logo is centered
            self.assertTrue(
                NxSigShell().intro.startswith(
                    "\n" + " " * 16 + "         __"
                )
            )
            for line in (
                "ls trades SOXL",
                "ls trades",
                "ls stocks",
                "help",
                "help ladder",
                "ls tasks",
            ):
                self.run_cmd(line)
        xtop = _xtop_lines(
            self.prices, None, None, 5, False
        )
        self.assertEqual(xtop[1], "-" * 47)
        with mock.patch.dict(
            config.DATA, {"terminal": {"width": 80}}
        ):
            xtop = _xtop_lines(
                self.prices, None, None, 5, False
            )
        self.assertTrue(all(len(l) <= 80 for l in xtop))
        self.assertEqual(len(xtop[1]), len(xtop[0]))
        self.assertEqual(
            xtop[4],
            "total" + " " * 43 + "+50.00      +24.39%",
        )

    # ---------------- chart ----------------

    def test_chart(self):
        start = datetime(2026, 10, 12, 9, 0)
        self.bars = [
            (start + timedelta(hours=i), p)
            for i, p in enumerate(
                [10, 12, 14, 16, 18, 16, 14]
            )
        ]
        # a buy at 10:00, written with a fixed date
        with open(
            os.path.join(storage.DB_DIR, "soxl_trades.csv"),
            "w",
        ) as f:
            f.write(
                "Id,Date,Time,Type,Count,Price\n"
                "1,12.10.2026,10:00,BUY,2,12.0\n"
            )
        # pinned with 9 rows, config "terminal"
        # "chart_height"
        with mock.patch.dict(
            config.DATA,
            {"terminal": {"chart_height": 9}},
        ):
            out = self.lines("chart soxl")
        self.assertEqual(
            out,
            [
                "SOXL 5 days, 15m bars   14.00  +40.00%",
                "18.00 |                       ***",
                "17.00 |                    ***   ***",
                "16.00 |                 ***         ***",
                "15.00 |              ***"
                "               ***",
                "14.00 |           ***"
                "                     **",
                "13.00 |        ***",
                "12.00 |.....*B*" + "." * 29 + " avg",
                "11.00 |  ***",
                "10.00 |**",
                "      +" + "-" * 37,
                "       12.10",
                "* price  B buy  . avg buy 12.00",
            ],
        )
        self.run_cmd("chart SOXL period 3 months")
        self.assertEqual(
            self.bars_calls,
            [("SOXL", 5, "15Min"), ("SOXL", 90, "1Day")],
        )

    def test_chart_errors(self):
        self.assertEqual(
            self.lines("chart"),
            [
                "usage: chart <stock> [period <n>",
                "  <days|weeks|months>]",
            ],
        )
        self.assertEqual(
            self.lines("chart ABC")[0],
            "error: unknown stock 'ABC', expected one of:",
        )
        self.assertEqual(
            self.lines("chart SOXL period 5 years"),
            [
                "error: the period is 'period <n>",
                "  <days|weeks|months>', e.g. 'period 3 "
                "months'",
            ],
        )
        self.assertEqual(
            self.lines("chart SOXL"),
            ["no prices for SOXL in the last 5 days"],
        )
        self.bars = requests.ConnectionError("no network")
        self.assertEqual(
            self.lines("chart SOXL period 1 week"),
            ["error: can't get the prices: no network"],
        )

        def missing_key():
            raise KeyError("APCA_API_KEY_ID")

        with mock.patch.object(
            prices, "_headers", missing_key
        ):
            self.assertEqual(
                self.lines("chart SOXL"),
                [
                    "error: missing APCA_API_KEY_ID in "
                    ".env, "
                    "can't",
                    "  get the prices",
                ],
            )
        # no request for a wrong command
        self.assertEqual(
            self.bars_calls,
            [("SOXL", 5, "15Min"), ("SOXL", 7, "15Min")],
        )

    def test_bars_request(self):
        pages = [
            {
                "bars": {
                    "SOXL": [
                        {
                            "t": "2026-10-12T13:00:00Z",
                            "c": 10.5,
                        }
                    ]
                },
                "next_page_token": "abc",
            },
            {
                "bars": {
                    "SOXL": [
                        {
                            "t": "2026-10-12T14:00:00Z",
                            "c": 11,
                        }
                    ]
                },
                "next_page_token": None,
            },
        ]
        calls = []

        def fake_get(url, params, headers, timeout):
            calls.append(dict(params))
            response = mock.Mock()
            response.json.return_value = pages[
                len(calls) - 1
            ]
            return response

        with mock.patch.object(
            prices.requests, "get", fake_get
        ):
            bars = REAL_BARS({}, "SOXL", 5, "1Hour")
        first = datetime(
            2026, 10, 12, 13, tzinfo=timezone.utc
        )
        local = first.astimezone().replace(tzinfo=None)
        self.assertEqual(
            bars,
            [
                (local, 10.5),
                (local + timedelta(hours=1), 11.0),
            ],
        )
        self.assertEqual(calls[0]["feed"], "sip")
        self.assertEqual(calls[0]["timeframe"], "1Hour")
        self.assertNotIn("page_token", calls[0])
        self.assertEqual(calls[1]["page_token"], "abc")
        start = datetime.strptime(
            calls[0]["start"], "%Y-%m-%dT%H:%M:%SZ"
        )
        end = datetime.strptime(
            calls[0]["end"], "%Y-%m-%dT%H:%M:%SZ"
        )
        self.assertEqual(end - start, timedelta(days=5))
        # the newest 15 minutes are left out
        now = datetime.now(timezone.utc).replace(
            tzinfo=None
        )
        self.assertGreater(now - end, timedelta(minutes=15))

    def test_complete_chart(self):
        self.assertIn("SOXL", self.complete("chart "))
        self.assertEqual(
            self.complete("chart SOXL "), ["period"]
        )
        self.assertEqual(
            self.complete("chart SOXL period 3 m"),
            ["months"],
        )

    # ---------------- terminal ----------------

    def test_test_notify(self):
        sent = []
        with mock.patch.object(
            telegram_notify, "notify", sent.append
        ):
            self.assertEqual(
                self.lines("test notify ladder"),
                ["sent a test ladder message (telegram)"],
            )
            self.assertEqual(
                self.lines("test NOTIFY Alert"),
                ["sent a test alert message (telegram)"],
            )
        stock = config.indices()[0]
        self.assertEqual(
            sent,
            [
                f"test: {stock} down to 89.50, passed 90 "
                "(ladder 0, next 80)",
                f"test: {stock} -10.5% at 17.90, bought "
                "at 20 (alert 0: down 10%)",
            ],
        )
        usage = [USAGE_NOTIFY]
        for line in ("test", "test notify", "test x y"):
            self.assertEqual(self.lines(line), usage, line)
        self.assertEqual(
            self.lines("test notify mail"),
            ["unknown kind 'mail', expected alert/ladder"],
        )

        def fail(text):
            raise RuntimeError("no network")

        with mock.patch.object(
            telegram_notify, "notify", fail
        ):
            self.assertEqual(
                self.lines("test notify alert"),
                ["error: could not send: no network"],
            )
        with mock.patch.dict(os.environ, {"TOKEN": ""}):
            self.assertEqual(
                self.lines("test notify alert"),
                [
                    "error: Telegram isn't set up, add "
                    "TOKEN and",
                    "  CHAT_ID to .env",
                ],
            )
        self.assertEqual(self.complete("test "), ["notify"])
        self.assertEqual(
            self.complete("test notify "),
            ["alert", "ladder"],
        )
        self.assertEqual(
            self.complete("test notify alert "), ["repeat"]
        )

    def test_test_notify_repeat(self):
        sent = []
        with mock.patch.object(
            telegram_notify,
            "notify",
            lambda text, key=None: sent.append((text, key)),
        ), mock.patch.object(
            shell.notify_cmd.time, "sleep"
        ) as sleep:
            out = self.lines("test notify alert repeat 3")
        self.assertEqual(
            out,
            [
                "sent 1/3",
                "sent 2/3",
                "sent 3/3",
                "sent a test alert message (telegram) 3 "
                "times, id",
                "  test",
            ],
        )
        self.assertEqual(
            [(t[-5:], k) for t, k in sent],
            [
                ("[1/3]", "test"),
                ("[2/3]", "test"),
                ("[3/3]", "test"),
            ],
        )
        self.assertEqual(sleep.call_count, 2)
        for bad in ("0", "21", "x"):
            line = f"test notify alert repeat {bad}"
            self.assertEqual(
                self.lines(line),
                [f"repeat must be 1-20, not '{bad}'"],
            )
        self.assertEqual(
            self.lines("test notify alert repeat"),
            [USAGE_NOTIFY],
        )

    def test_terminal_info(self):
        name = tasks_owner.this_device()["name"]
        with mock.patch.dict(
            os.environ,
            {"TERMUX_VERSION": "0.118", "TERM": "xterm"},
        ), mock.patch.object(
            shell.terminal_cmd,
            "_output",
            lambda args: {
                "device_name": "Galaxy S23 Ultra",
                "ro.product.manufacturer": "samsung",
                "ro.product.model": "SM-S918B",
            }[args[-1]],
        ):
            out = self.lines("terminal info")
        self.assertEqual(
            out,
            [
                "terminal:   Termux 0.118",
                "size:       - (the output is "
                "not a terminal)",
                "width:      48 (default)",
                "theme:      colored (default), "
                "no colors now:",
                "            NO_COLOR is set",
                "colors:     basic (TERM xterm)",
                # the test's output has no encoding
                "encoding:   -",
                out[7],
                out[8],
                f"device:     {name}",
                "model:      Galaxy S23 Ultra (SM-S918B)",
            ],
        )
        self.assertTrue(out[7].startswith("completion: "))
        self.assertTrue(out[8].startswith("python:     3."))

    def test_terminal_model(self):
        model = shell.terminal_cmd._model
        outputs = {"device_name": "My phone"}

        def output(args):
            return outputs.get(args[-1], "")

        with mock.patch.dict(
            os.environ, {"TERMUX_VERSION": "0.118"}
        ), mock.patch.object(
            shell.terminal_cmd, "_output", output
        ):
            self.assertEqual(model(), "My phone")
            outputs["ro.product.model"] = "Pixel 8"
            self.assertEqual(model(), "My phone (Pixel 8)")
            # the model isn't repeated
            outputs["device_name"] = "Pixel 8"
            self.assertEqual(model(), "Pixel 8")
            # Android doesn't let Termux read the name
            outputs = {"ro.product.manufacturer": "Google"}
            outputs["ro.product.model"] = "Pixel 8"
            self.assertEqual(model(), "Google Pixel 8")
            # the maker isn't repeated
            outputs["ro.product.model"] = "google Pixel"
            self.assertEqual(model(), "google Pixel")
            outputs.clear()
            self.assertEqual(model(), "-")
        env = dict(os.environ)
        env.pop("TERMUX_VERSION", None)
        dmi = {"sys_vendor": "LENOVO"}
        with mock.patch.dict(
            os.environ, env, clear=True
        ), mock.patch.object(
            shell.terminal_cmd,
            "_dmi",
            lambda name: dmi.get(name, ""),
        ):
            dmi["product_name"] = "20XW0026GE"
            self.assertEqual(model(), "LENOVO 20XW0026GE")

    def test_theme(self):
        from shell import ui

        tty = mock.patch.object(
            ui.sys.stdout, "isatty", lambda: True
        )
        with tty, mock.patch.dict(os.environ):
            os.environ.pop("NO_COLOR")
            self.assertTrue(ui.supports_color())
            with mock.patch.dict(
                config.DATA,
                {"terminal": {"theme": "plain"}},
            ):
                self.assertFalse(ui.supports_color())
                self.assertEqual(
                    ui.color_off_reason(),
                    "the theme is plain",
                )
                # .env has no say
                os.environ["NX_THEME"] = "colored"
                self.assertFalse(ui.supports_color())
        with mock.patch.dict(
            config.DATA, {"terminal": {"theme": "dark"}}
        ):
            self.assertEqual(ui.theme(), "colored")
            self.assertEqual(
                ui.setting_problems(),
                [
                    "theme 'dark' (config.json) is not "
                    "colored or plain, using colored"
                ],
            )

    def test_complete_terminal(self):
        self.assertEqual(
            self.complete("terminal "), ["info"]
        )
        self.assertEqual(
            self.lines("terminal set theme plain"),
            ["usage: terminal info, see 'help terminal'"],
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

    def test_cmd_files_use_engines(self):
        # these *_cmd.py files reach the data only
        # through engines, never storage; the others
        # follow (TODO.md, "One engine per kind of
        # data")
        import ast

        clean = [
            "alert_cmd.py",
            "base_trade_cmd.py",
            "chart_cmd.py",
            "ladder_cmd.py",
            "stocks_cmd.py",
            "rule_cmd.py",
            "tasks_cmd.py",
            "trade_cmd.py",
        ]
        folder = os.path.join(
            storage.ROOT_DIR, "scripts", "shell"
        )
        for name in clean:
            with open(os.path.join(folder, name)) as f:
                tree = ast.parse(f.read())
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported |= {
                        a.name.split(".")[0]
                        for a in node.names
                    }
                elif isinstance(node, ast.ImportFrom):
                    imported.add(
                        (node.module or "").split(".")[0]
                    )
            self.assertFalse(
                imported & {"storage"},
                f"{name} imports {imported}",
            )

    def test_ladder_and_alerts_separate(self):
        # neither engine imports the other, they share
        # only process.py
        import ast

        folder = os.path.join(storage.ROOT_DIR, "scripts")
        for name, other in (
            ("engines/ladder.py", "alerts"),
            ("services/ladder_service.py", "alerts"),
            ("engines/alerts.py", "ladder"),
            ("services/alert_service.py", "ladder"),
        ):
            with open(os.path.join(folder, name)) as f:
                tree = ast.parse(f.read())
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported |= {a.name for a in node.names}
                elif isinstance(node, ast.ImportFrom):
                    imported.add(node.module or "")
            self.assertNotIn(other, imported, name)

    def test_collected_modules(self):
        self.assertEqual(
            list(self.shell.objects),
            [
                "stocks",
                "trade",
                "ladder",
                "rule",
                "basetrade",
                "alert",
                "mail-broker",
                "task",
            ],
        )
        data = [
            "trade",
            "ladder",
            "rule",
            "basetrade",
            "alert",
        ]
        tasks = ["ladder", "alert", "mail-broker"]
        self.assertEqual(
            self.shell.actions,
            {
                "ls": ["stocks"] + data + ["task"],
                "add": data,
                "rm": data,
                "run": tasks,
                "stop": tasks + ["task"],
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
                "alerts",
                "tasks",
            ],
        )
        self.assertEqual(
            self.complete("ls la"), ["ladders"]
        )
        self.assertEqual(
            self.complete("ls basetrades "),
            ["sip", "iex", "al"],
        )
        self.assertEqual(
            self.complete("ls basetrades sip "), ["al"]
        )
        self.assertEqual(
            self.complete("ls trades so"), ["SOXL"]
        )
        self.assertEqual(
            self.complete("add "),
            [
                "trade",
                "ladder",
                "rule",
                "basetrade",
                "alert",
            ],
        )
        self.assertEqual(
            self.complete("add trade SOXL "),
            ["buy", "sell"],
        )
        self.assertEqual(
            self.complete("add trade fr"), ["from"]
        )
        self.assertEqual(
            self.complete("add trade from "), []
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
            self.complete("add basetrade al"), ["all"]
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
            self.complete("run "),
            ["ladder", "alerts", "mail-broker"],
        )
        self.assertEqual(
            self.complete("add alert "),
            ["basetrades", "gain"],
        )
        self.assertEqual(
            self.complete("add alert gain ts"), ["TSMX"]
        )
        self.assertEqual(
            self.complete("add alert gain al"), ["all"]
        )
        self.assertEqual(
            self.complete("add alert gain all 10 "),
            ["percent"],
        )
        self.assertEqual(
            self.complete("add alert basetrades down 5 "),
            ["percent"],
        )
        self.assertEqual(self.complete("run x "), [])
        self.assertEqual(self.complete("help ad"), ["add"])
        self.assertEqual(
            self.complete("help al"), ["alert", "alerts"]
        )
        self.assertEqual(
            self.complete("help add "),
            [
                "trade",
                "ladder",
                "rule",
                "basetrade",
                "alert",
            ],
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


class ConfigTest(unittest.TestCase):
    """the shipped config.json, as the scripts read it"""

    def setUp(self):
        path = os.path.join(storage.ROOT_DIR, "config.json")
        with open(path) as f:
            self.file = json.load(f)

    def test_scripts_read_it(self):
        self.assertEqual(config.DATA, self.file)
        self.assertEqual(
            storage.DB_DIR, config.storage_dir()
        )
        self.assertEqual(
            [s.name for s in storage.Stock],
            self.file["indices"],
        )
        self.assertTrue(self.file["indices"])
        for name in self.file["indices"]:
            self.assertIsInstance(name, str)
        for key in ("url", "feed", "storage_dir"):
            self.assertIsInstance(self.file[key], str)

    def test_timing(self):
        timing = self.file["timing"]
        for key in ("ladder_interval", "alert_interval"):
            self.assertIsInstance(timing[key], (int, float))
            self.assertGreater(timing[key], 0)
        self.assertEqual(
            ladder.INTERVAL, timing["ladder_interval"]
        )
        self.assertEqual(
            alerts.INTERVAL, timing["alert_interval"]
        )

    def test_notify(self):
        name = self.file["notify"]
        self.assertIn(name, notifier.CHANNELS)
        self.assertEqual(notifier.NAME, name)

    def test_terminal(self):
        from shell import ui

        terminal = self.file["terminal"]
        self.assertEqual(
            ui.width_setting(),
            (terminal["width"], "config.json"),
        )
        self.assertEqual(
            ui.theme_setting(),
            (terminal["theme"], "config.json"),
        )
        with mock.patch.dict(os.environ, {"COLUMNS": "80"}):
            self.assertEqual(ui.setting_problems(), [])
        self.assertEqual(
            config.chart_height(), terminal["chart_height"]
        )


if __name__ == "__main__":
    unittest.main()

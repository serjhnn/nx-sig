# tests of scripts/engines/statement.py
#
#   python tests/test_statement.py

import os
import tempfile
import unittest

import paths  # noqa: F401, scripts/ on sys.path
from engines.statement import parse_rows, parse_statement
from storage import TradeType

# the three rows of a real statement: a sell (its order
# text split over two lines), a buy and the buy's fee
SAMPLE = (
    '"10/12/25, 23:34","10/12/25, 23:34",'
    '"Փոխանցում հաշվին","XNT LTD",'
    '"Պատվեր թիվ 460827, 2025/12/10,\n'
    ' 14.00 հատ VOO վաճառք",'
    '"+8,834.00 USD","+8,834.00 USD"\n'
    '"22/10/26, 19:46","22/10/26, 19:46",'
    '"Փոխանցում հաշվին",'
    '"GTN EUROPE FINANCIAL SERVICES LI",'
    '"Պատվեր թիվ 699534, 2026/10/22, 10.00 հատ AVGG'
    ' առք","-182.19 USD","-182.19 USD"\n'
    '"22/10/26, 19:46","22/10/26, 19:46",'
    '"Արտարժույթի փոխանակում",'
    '"Տարանցիկ հաշիվ/բրոք.ծառայութ./ԱԱՀ հարկվող/",'
    '"Միջնորդավճար / Պատվեր թիվ 699534, 2026/10/22,'
    ' 10.00 հատ AVGG առք","-5.00 USD","-5.00 USD"\n'
)

VOO = {
    "Stock": "VOO",
    "Order": 460827,
    "Date": "10.12.2025",
    "Time": "23:34",
    "Type": TradeType.SELL,
    "Count": 14,
    "Price": 631.0,
}

AVGG = {
    "Stock": "AVGG",
    "Order": 699534,
    "Date": "22.10.2026",
    "Time": "19:46",
    "Type": TradeType.BUY,
    "Count": 10,
    "Price": 18.219,
}


def row(
    text,
    amount="-100.00 USD",
    date="22/10/26, 19:46",
):
    """a statement row with the columns the parser
    reads"""
    return [date, date, "x", "y", text, amount, amount]


def order(number=1, count="10.00", side="առք"):
    return (
        f"Պատվեր թիվ {number}, 2026/10/22, "
        f"{count} հատ AVGG {side}"
    )


class ParseStatementTest(unittest.TestCase):
    def test_sample_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "statement.csv")
            with open(path, "w", encoding="utf-8") as f:
                f.write(SAMPLE)
            trades, skipped = parse_statement(path)
        self.assertEqual(trades, [VOO, AVGG])
        self.assertEqual(skipped, [])

    def test_byte_order_mark(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "statement.csv")
            with open(path, "w", encoding="utf-8-sig") as f:
                f.write(SAMPLE)
            trades, _ = parse_statement(path)
        self.assertEqual(trades, [VOO, AVGG])

    def test_empty_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "statement.csv")
            open(path, "w").close()
            self.assertEqual(
                parse_statement(path), ([], [])
            )


class ParseRowsTest(unittest.TestCase):
    def test_buy(self):
        trades, _ = parse_rows([row(order())])
        self.assertEqual(trades[0]["Type"], TradeType.BUY)
        self.assertEqual(trades[0]["Price"], 10.0)

    def test_sell(self):
        rows = [row(order(side="վաճառք"), "+100.00 USD")]
        trades, _ = parse_rows(rows)
        self.assertEqual(trades[0]["Type"], TradeType.SELL)

    def test_thousands_and_rounding(self):
        rows = [row(order(count="3.00"), "-1,000.00 USD")]
        trades, _ = parse_rows(rows)
        self.assertEqual(trades[0]["Price"], 333.3333)

    def test_extra_spaces(self):
        text = order().replace(" ", "  ")
        trades, _ = parse_rows([row(" " + text + " ")])
        self.assertEqual(len(trades), 1)

    def test_rows_that_are_no_order_are_left_out(self):
        rows = [
            ["Date", "Value date", "Type", "Name"],
            row("Միջնորդավճար / " + order()),
            row("Փոխանցում"),
            [],
            ["only", "three", "columns"],
        ]
        self.assertEqual(parse_rows(rows), ([], []))

    def test_skipped_with_reason(self):
        rows = [
            row(order(1, count="1.50")),
            row(order(2, count="0.00")),
            row(order(3), "+100.00 USD"),
            row(order(4, side="վաճառք"), "-100.00 USD"),
            row(order(5), "0.00 USD"),
            row(order(6), "USD"),
            row(order(7), ""),
            row(order(8), date="31/02/26, 10:00"),
            row(order(9), date="2026-10-22"),
            row("Պատվեր թիվ 10, 10 հատ AVGG առք"),
            row(order(11))[:5],
        ]
        trades, skipped = parse_rows(rows)
        self.assertEqual(trades, [])
        self.assertEqual(
            [number for number, _ in skipped],
            list(range(1, 12)),
        )
        self.assertEqual(skipped[0], (1, "count 1.50"))
        self.assertEqual(
            skipped[2], (3, "amount +100.00 USD")
        )
        self.assertEqual(skipped[6], (7, "no amount"))
        self.assertEqual(
            skipped[7], (8, "date 31/02/26, 10:00")
        )
        self.assertEqual(
            skipped[9], (10, "not an order text")
        )

    def test_a_bad_row_keeps_the_others(self):
        rows = [
            row(order(1, count="1.50")),
            row(order(2)),
        ]
        trades, skipped = parse_rows(rows)
        self.assertEqual(trades[0]["Order"], 2)
        self.assertEqual(len(skipped), 1)

    def test_oldest_first(self):
        # a statement lists the newest first
        rows = [
            row(order(3), date="23/10/26, 09:00"),
            row(order(2), date="22/10/26, 19:46"),
            row(order(1), date="22/10/26, 19:46"),
            row(order(0), date="10/12/25, 23:34"),
        ]
        trades, _ = parse_rows(rows)
        self.assertEqual(
            [t["Order"] for t in trades], [0, 1, 2, 3]
        )

    def test_lowercase_symbol(self):
        text = order().replace("AVGG", "avgg")
        trades, _ = parse_rows([row(text)])
        self.assertEqual(trades[0]["Stock"], "AVGG")


if __name__ == "__main__":
    unittest.main()

# tests of scripts/mtsig/order_parser.py
#
#   python tests/test_order_parser.py

import unittest

import paths  # noqa: F401, scripts/ on sys.path
from order_parser import (
    parse_order,
)

EXAMPLE = """Symbol (Ծածկագիր) TSMX
Quantity (քանակ) 10
Submitting Date (տրման ամսաթիվ) 2026 Oct 09 08:02:13
Submitted Price (գին) 87.54
Executed Date (կատարման ամսաթիվ) 2026 Oct 09 08:02:56
Executed Price (կատարման գին) 87.54
Order Type (պատվերի տեսակ) Buy  LMT  DAY
Status (կարգավիճակ) *FILLED*"""


class OrderParserTest(unittest.TestCase):
    def test_example(self):
        self.assertEqual(
            parse_order(EXAMPLE),
            {
                "symbol": "TSMX",
                "quantity": 10,
                "executed price": 87.54,
                "order type": "buy",
                "status": "FILLED",
            },
        )

    def test_executed_price_not_submitted_price(self):
        text = EXAMPLE.replace(
            "Executed Price (կատարման գին) 87.54",
            "Executed Price (կատարման գին) 87.10",
        )
        self.assertEqual(
            parse_order(text)["executed price"], 87.10
        )

    def test_sell_and_other_status(self):
        text = EXAMPLE.replace(
            "Buy  LMT  DAY", "Sell  MKT  GTC"
        ).replace("*FILLED*", "*CANCELLED*")
        order = parse_order(text)
        self.assertEqual(order["order type"], "sell")
        self.assertEqual(order["status"], "CANCELLED")

    def test_extra_text_and_indentation(self):
        text = (
            "Dear client,\n\n   "
            + EXAMPLE.replace("\n", "\n   ")
            + "\n\nBest regards"
        )
        self.assertEqual(
            parse_order(text)["symbol"], "TSMX"
        )
        self.assertEqual(parse_order(text)["quantity"], 10)

    def test_value_on_next_line(self):
        text = (
            "Symbol (Ծածկագիր)\nTSMX\n"
            "Quantity (քանակ)\n1,000\n"
        )
        order = parse_order(text)
        self.assertEqual(order["symbol"], "TSMX")
        self.assertEqual(order["quantity"], 1000)

    def test_empty_value_does_not_take_next_field(self):
        text = EXAMPLE.replace(
            "Executed Price (կատարման գին) 87.54",
            "Executed Price (կատարման գին)",
        )
        text = text.replace(
            "Symbol (Ծածկագիր) TSMX",
            "Symbol (Ծածկագիր)",
        )
        order = parse_order(text)
        self.assertIsNone(order["executed price"])
        self.assertIsNone(order["symbol"])
        self.assertEqual(order["quantity"], 10)

    def test_missing_fields_are_none(self):
        order = parse_order("Symbol (Ծածկագիր) TSMX")
        self.assertEqual(order["symbol"], "TSMX")
        self.assertIsNone(order["quantity"])
        self.assertIsNone(order["executed price"])
        self.assertIsNone(order["order type"])
        self.assertIsNone(order["status"])


print(parse_order(EXAMPLE))
if __name__ == "__main__":
    unittest.main()

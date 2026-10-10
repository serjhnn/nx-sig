# parse broker order emails
#
# public functions:
#   parse_order(text)
#       find the order fields in an email text like the one below and return
#       {"symbol": str, "quantity": int, "executed price": float,
#        "order type": "buy"/"sell", "status": str}
#       a field that is not found is None
#
# message example:
#   Symbol (Ծածկագիր) TSMX
#   Quantity (քանակ) 10
#   Submitting Date (տրման ամսաթիվ) 2026 Oct 09 08:02:13
#   Submitted Price (գին) 87.54
#   Executed Date (կատարման ամսաթիվ) 2026 Oct 09 08:02:56
#   Executed Price (կատարման գին) 87.54
#   Order Type (պատվերի տեսակ) Buy  LMT  DAY
#   Status (կարգավիճակ) *FILLED*

import re

# English label of each field in the email, the translation in brackets is optional
LABELS = {
    "symbol": "Symbol",
    "quantity": "Quantity",
    "executed price": "Executed Price",
    "order type": "Order Type",
    "status": "Status",
}


def parse_order(text):
    lines = [line.strip() for line in text.splitlines()]
    order = {}
    for key, label in LABELS.items():
        raw = _field_value(lines, label)
        order[key] = _convert(key, raw) if raw else None
    return order


def _field_value(lines, label):
    """return the text after 'Label (translation)', or the next line if it is empty"""
    pattern = re.compile(rf"^{re.escape(label)}\s*(?:\([^)]*\))?\s*:?\s*(.*)$", re.IGNORECASE)
    for i, line in enumerate(lines):
        match = pattern.match(line)
        if not match:
            continue
        value = match.group(1).strip()
        if value:
            return value
        # value on its own line, e.g. when the email is an html table,
        # unless that line is already the next field ('Order Type (...) ...')
        following = next((l for l in lines[i + 1:] if l), None)
        if following is None or _LABEL_LINE.match(following):
            return None
        return following
    return None


# a 'Label (translation) ...' line of any field
_LABEL_LINE = re.compile(r"^[A-Za-z][A-Za-z ]*\([^)]*\)")


def _convert(key, raw):
    try:
        if key == "symbol":
            return raw.split()[0].upper()
        if key == "quantity":
            return int(float(raw.split()[0].replace(",", "")))
        if key == "executed price":
            return float(raw.split()[0].replace(",", ""))
        if key == "order type":
            # 'Buy  LMT  DAY' -> 'buy', the order kind and duration are not needed
            side = raw.split()[0].lower()
            return side if side in ("buy", "sell") else None
        if key == "status":
            return raw.strip("* ").upper()
    except (ValueError, IndexError):
        return None
    return raw


if __name__ == "__main__":
    import unittest

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
            self.assertEqual(parse_order(EXAMPLE), {
                "symbol": "TSMX",
                "quantity": 10,
                "executed price": 87.54,
                "order type": "buy",
                "status": "FILLED",
            })

        def test_executed_price_not_submitted_price(self):
            text = EXAMPLE.replace("Executed Price (կատարման գին) 87.54",
                                   "Executed Price (կատարման գին) 87.10")
            self.assertEqual(parse_order(text)["executed price"], 87.10)

        def test_sell_and_other_status(self):
            text = (EXAMPLE.replace("Buy  LMT  DAY", "Sell  MKT  GTC")
                           .replace("*FILLED*", "*CANCELLED*"))
            order = parse_order(text)
            self.assertEqual(order["order type"], "sell")
            self.assertEqual(order["status"], "CANCELLED")

        def test_extra_text_and_indentation(self):
            text = "Dear client,\n\n   " + EXAMPLE.replace("\n", "\n   ") + "\n\nBest regards"
            self.assertEqual(parse_order(text)["symbol"], "TSMX")
            self.assertEqual(parse_order(text)["quantity"], 10)

        def test_value_on_next_line(self):
            text = "Symbol (Ծածկագիր)\nTSMX\nQuantity (քանակ)\n1,000\n"
            order = parse_order(text)
            self.assertEqual(order["symbol"], "TSMX")
            self.assertEqual(order["quantity"], 1000)

        def test_empty_value_does_not_take_next_field(self):
            text = EXAMPLE.replace("Executed Price (կատարման գին) 87.54", "Executed Price (կատարման գին)")
            text = text.replace("Symbol (Ծածկագիր) TSMX", "Symbol (Ծածկագիր)")
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
    unittest.main()

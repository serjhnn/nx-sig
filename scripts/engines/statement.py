# statement: read the trades out of a bank statement csv
#
#   python tests/test_statement.py   the tests
#
# public functions:
#   parse_statement(path)
#       (trades, skipped) of the statement file
#   parse_rows(rows)
#       the same for rows already read (lists of str)
#
# a trade is {"Stock": str, "Order": int, "Date":
# "dd.mm.yyyy", "Time": "hh:mm", "Type": TradeType,
# "Count": int, "Price": float}, oldest first. skipped
# is [(row number, reason)] of the order rows that
# could not be read; rows that are no order (fees,
# transfers, headers) are left out without a reason.
#
# row example (columns 1, 5 and 6 are used):
#   "22/10/26, 19:46","22/10/26, 19:46",
#   "Փոխանցում հաշվին","GTN EUROPE ...",
#   "Պատվեր թիվ 699534, 2026/10/22, 10.00 հատ AVGG
#   առք","-182.19 USD","-182.19 USD"
#
# the price is the amount / count; the fee is a row of
# its own ("Միջնորդավճար / Պատվեր ...") and is left out

import csv
import re
from datetime import datetime

from storage import TradeType

# column numbers, from 0
DATE_COL, TEXT_COL, AMOUNT_COL = 0, 4, 5

# the order text starts with this
ORDER_START = "Պատվեր թիվ"

# whole order text, spaces already made single
_ORDER = re.compile(
    r"^Պատվեր թիվ (\d+), \d{4}/\d{2}/\d{2}, "
    r"([\d.,]+) հատ ([A-Za-z0-9.]+) (առք|վաճառք)$"
)

# "22/10/26, 19:46"
_DATE = re.compile(
    r"^(\d{2})/(\d{2})/(\d{2}),\s*(\d{2}):(\d{2})$"
)

_TYPES = {"առք": TradeType.BUY, "վաճառք": TradeType.SELL}


def parse_statement(path):
    # utf-8-sig drops a byte order mark if there is one
    with open(path, newline="", encoding="utf-8-sig") as f:
        return parse_rows(csv.reader(f))


def parse_rows(rows):
    trades, skipped = [], []
    for number, row in enumerate(rows, start=1):
        if len(row) <= TEXT_COL:
            continue
        text = " ".join(row[TEXT_COL].split())
        if not text.startswith(ORDER_START):
            continue
        try:
            trades.append(_trade(row, text))
        except ValueError as e:
            skipped.append((number, str(e)))
    trades.sort(key=_order_key)
    return trades, skipped


def _trade(row, text):
    """the trade of an order row, ValueError if it
    can't be read"""
    match = _ORDER.match(text)
    if not match:
        raise ValueError("not an order text")
    order, raw_count, symbol, side = match.groups()
    trade_type = _TYPES[side]

    count = _number(raw_count)
    if count <= 0 or count != int(count):
        raise ValueError(f"count {raw_count}")
    count = int(count)

    if len(row) <= AMOUNT_COL:
        raise ValueError("no amount")
    amount = _amount(row[AMOUNT_COL])
    # a buy takes money from the account, a sell adds
    if amount == 0 or (amount < 0) != (
        trade_type == TradeType.BUY
    ):
        raise ValueError(f"amount {row[AMOUNT_COL]}")

    date, time = _date_time(row[DATE_COL])
    return {
        "Stock": symbol.upper(),
        "Order": int(order),
        "Date": date,
        "Time": time,
        "Type": trade_type,
        "Count": count,
        "Price": round(abs(amount) / count, 4),
    }


def _amount(raw):
    """'-1,182.19 USD' -> -1182.19"""
    parts = raw.split()
    if not parts:
        raise ValueError("no amount")
    try:
        return _number(parts[0])
    except ValueError:
        raise ValueError(f"amount {raw}") from None


def _number(raw):
    return float(raw.replace(",", ""))


def _date_time(raw):
    """'22/10/26, 19:46' -> ('22.10.2026', '19:46')"""
    match = _DATE.match(raw.strip())
    if not match:
        raise ValueError(f"date {raw}")
    day, month, year, hour, minute = match.groups()
    try:
        datetime(
            2000 + int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
        )
    except ValueError:
        raise ValueError(f"date {raw}") from None
    return (
        f"{day}.{month}.20{year}",
        f"{hour}:{minute}",
    )


def _order_key(trade):
    """oldest first; trades of the same minute by
    order number"""
    when = datetime.strptime(
        f"{trade['Date']} {trade['Time']}",
        "%d.%m.%Y %H:%M",
    )
    return when, trade["Order"]

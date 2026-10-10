# order watcher: records broker order emails as transactions
#
# runs as its own process, next to the CLI:
#   python order_watcher.py        (needs Python 3.14+, see mail_reader.py)
#
# waits for emails from IMAP_SENDER (.env), parses them with order_parser.py
# and records FILLED orders of the config "indices" with
# nx_sig_db.transactions_add_one(). other emails are logged and skipped.
#
# the last handled email is kept in {storage_dir}/mail_state.json, so after a
# restart it picks up the emails it missed and never records an order twice.
# a heartbeat is kept in {storage_dir}/watcher_status.json for the CLI 'status'.

import html
import os
import re
from datetime import datetime

from mail_reader import message_text, watch_sender_emails
from nx_sig_db import (
    Stock,
    TransactionType,
    mail_position_get,
    mail_position_set,
    transactions_add_one,
    watcher_status_get,
    watcher_status_set,
)
from order_parser import parse_order

STARTED = datetime.now().isoformat(timespec="seconds")
_last_order = None


def handle_email(message):
    """record the order in the email if it is a FILLED order of a known stock"""
    global _last_order
    subject = message.get("Subject", "")
    order = parse_order(_to_text(message_text(message)))
    reason = _skip_reason(order)
    if reason:
        _log(f"skipped email '{subject}': {reason} {order}")
        return

    stock = Stock[order["symbol"]]
    transaction_type = TransactionType[order["order type"].upper()]
    transactions_add_one(stock, transaction_type, order["quantity"], order["executed price"])
    _last_order = f"{transaction_type.name} {order['quantity']} {stock.name} @ {order['executed price']}"
    _log(f"recorded {_last_order}")
    _status("waiting")


def _skip_reason(order):
    if order["status"] != "FILLED":
        return f"status is {order['status']}, not FILLED"
    if order["symbol"] not in Stock.__members__:
        return f"symbol {order['symbol']} is not in config indices"
    if order["order type"] not in ("buy", "sell"):
        return "order type is not buy/sell"
    if not order["quantity"] or order["quantity"] <= 0:
        return "no quantity"
    if not order["executed price"] or order["executed price"] <= 0:
        return "no executed price"
    return None


def _to_text(body):
    """turn an html email body into lines of text that order_parser can read"""
    if "<" not in body or not re.search(r"<\s*(html|body|table|div|p|br|td)\b", body, re.IGNORECASE):
        return body
    body = re.sub(r"(?is)<(script|style).*?</\1>", "", body)
    # a table row 'Symbol (...) | TSMX' becomes one line 'Symbol (...) TSMX'
    body = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", body)
    body = re.sub(r"(?i)</t[dh]>", " ", body)
    body = re.sub(r"<[^>]+>", "", body)
    return html.unescape(body)


def _status(state):
    """write the heartbeat that the CLI 'status' command shows"""
    watcher_status_set({
        "pid": os.getpid(),
        "started": STARTED,
        "updated": datetime.now().isoformat(timespec="seconds"),
        "state": state,
        "last_order": _last_order,
    })


def _log(text):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {text}", flush=True)


def main():
    global _last_order
    # keep showing the last recorded order after a restart
    _last_order = (watcher_status_get() or {}).get("last_order")
    _status("starting")
    try:
        watch_sender_emails(
            handle_email,
            load_position=mail_position_get,
            save_position=mail_position_set,
            on_status=_status,
        )
    finally:
        _status("stopped")


if __name__ == "__main__":
    main()

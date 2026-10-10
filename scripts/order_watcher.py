# order watcher: records broker order emails as transactions
#
# runs as its own process, next to the CLI:
#   python scripts/order_watcher.py
#   (needs Python 3.14+, see mail_reader.py)
# or in the background:
#   ./watcher start | stop | status
#
# waits for emails from IMAP_SENDER (.env), parses them
# with order_parser.py and records FILLED orders of the
# config "indices" with storage.transactions_add_one().
# other emails are logged and skipped.
#
# the last handled email is kept in
# {storage_dir}/mail_state.json, so after a restart it
# picks up the emails it missed and never records an
# order twice. a heartbeat for the CLI 'status' is kept
# in {storage_dir}/watcher_status.json.
#
# logs: {storage_dir}/logs/order_watcher.log (and the
# console), rotated at 1 MB, the last 5 files are kept.
# LOG_LEVEL=DEBUG in .env adds every IDLE round, ignored
# emails and the parsed fields of each order.

import html
import logging
import logging.handlers
import os
import platform
import re
import signal
import sys
from datetime import datetime

import storage

from mail_reader import message_text, watch_sender_emails
from storage import (
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
LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 5
# how much of an email body is logged when it can't be
# parsed
BODY_EXCERPT = 1500

log = logging.getLogger("order_watcher")
_last_order = None
# {"time": iso time, "text": ...} of the last order that
# could not be recorded
_last_error = None


def handle_email(message):
    """record the order in the email if it is a FILLED
    order of a known stock"""
    global _last_order, _last_error
    subject = message.get("Subject", "")
    text = _to_text(message_text(message))
    order = parse_order(text)
    log.debug("parsed %r: %s", subject, order)

    if order["status"] is None or order["symbol"] is None:
        # not an order email, or the broker changed the
        # format: keep the text to diagnose
        log.warning(
            "could not parse an order from email %r: %s"
            "\n--- email text ---\n%s\n---",
            subject, order, text[:BODY_EXCERPT])
        return
    reason = _skip_reason(order)
    if reason:
        log.info("skipped %r: %s %s",
                 subject, reason, order)
        return

    stock = Stock[order["symbol"]]
    side = TransactionType[order["order type"].upper()]
    quantity = order["quantity"]
    price = order["executed price"]
    description = (f"{side.name} {quantity} "
                   f"{stock.name} @ {price}")
    try:
        transactions_add_one(stock, side, quantity, price)
    except Exception:
        # the email is not handled again, so say exactly
        # what is missing and how to add it
        command = (f"tr add {stock.name} "
                   f"{side.name.lower()} "
                   f"{quantity} {price}")
        log.exception(
            "ORDER NOT RECORDED: %s from email %r, "
            "add it manually in the CLI: %s",
            description, subject, command)
        _last_error = {
            "time": datetime.now().isoformat(
                timespec="seconds"),
            "text": (f"{description} not recorded, "
                     f"add with '{command}'"),
        }
        _status("waiting")
        return
    _last_order = description
    log.info("recorded %s (email %r, Message-ID %s)",
             _last_order, subject,
             message.get("Message-ID", "-"))
    _status("waiting")


def _skip_reason(order):
    if order["status"] != "FILLED":
        return f"status is {order['status']}, not FILLED"
    if order["symbol"] not in Stock.__members__:
        return (f"symbol {order['symbol']} "
                "is not in config indices")
    if order["order type"] not in ("buy", "sell"):
        return "order type is not buy/sell"
    if not order["quantity"] or order["quantity"] <= 0:
        return "no quantity"
    price = order["executed price"]
    if not price or price <= 0:
        return "no executed price"
    return None


# tags that mark an email body as html
_HTML_TAG = re.compile(
    r"<\s*(html|body|table|div|p|br|td)\b", re.IGNORECASE)


def _to_text(body):
    """turn an html email body into lines of text that
    order_parser can read"""
    if "<" not in body or not _HTML_TAG.search(body):
        return body
    body = re.sub(r"(?is)<(script|style).*?</\1>", "", body)
    # a table row 'Symbol (...) | TSMX' becomes one line
    # 'Symbol (...) TSMX'
    body = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>",
                  "\n", body)
    body = re.sub(r"(?i)</t[dh]>", " ", body)
    body = re.sub(r"<[^>]+>", "", body)
    return html.unescape(body)


def _status(state):
    """write the heartbeat that the CLI 'status' shows"""
    try:
        watcher_status_set({
            "pid": os.getpid(),
            "started": STARTED,
            "updated": datetime.now().isoformat(
                timespec="seconds"),
            "state": state,
            "last_order": _last_order,
            "last_error": _last_error,
            "log": _log_path(),
        })
    except Exception:
        log.exception("could not write the watcher status")


def _log_path():
    return os.path.abspath(os.path.join(
        storage.DB_DIR, "logs", "order_watcher.log"))


def setup_logging():
    """log to a rotating file in {storage_dir}/logs and
    to the console"""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    path = _log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT, encoding="utf-8")
    handlers = [file_handler]
    # the ./watcher script runs in the background and
    # sets LOG_CONSOLE=0
    if os.getenv("LOG_CONSOLE", "1") != "0":
        handlers.append(logging.StreamHandler())
    root = logging.getLogger()
    root.setLevel(level)
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)


def _stop_on_signal(signum, frame):
    # handled like Ctrl+C: the IMAP loop logs out and the
    # heartbeat says 'stopped'
    raise KeyboardInterrupt


def main():
    global _last_order, _last_error
    # a background process ignores SIGINT, so
    # ./watcher stop (and plain kill) send SIGTERM
    signal.signal(signal.SIGTERM, _stop_on_signal)
    signal.signal(signal.SIGINT, signal.default_int_handler)
    setup_logging()
    log.info("order watcher starting, pid %s, "
             "Python %s on %s, log %s",
             os.getpid(), platform.python_version(),
             platform.platform(), _log_path())
    # keep showing the last recorded order after a restart
    previous = watcher_status_get() or {}
    _last_order = previous.get("last_order")
    _last_error = previous.get("last_error")
    _status("starting")
    try:
        watch_sender_emails(
            handle_email,
            load_position=mail_position_get,
            save_position=mail_position_set,
            on_status=_status,
        )
    except Exception:
        # e.g. wrong password, missing .env settings,
        # old Python
        log.critical("order watcher crashed", exc_info=True)
        _status("crashed, see log")
        sys.exit(1)
    _status("stopped")
    log.info("order watcher stopped")


if __name__ == "__main__":
    main()

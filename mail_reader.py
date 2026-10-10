"""Fetch and print messages from an IMAP mailbox.

.env settings:
    IMAP_HOST, IMAP_USERNAME, IMAP_APP_PASSWORD
    IMAP_MAILBOX   (optional, default INBOX)
    IMAP_SENDER    email address that wait_for_sender_email() waits for
"""

import imaplib
import os
import time
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses

from dotenv import load_dotenv


load_dotenv()


def _message_text(message):
    """Return the first plain-text body, or a decoded fallback body."""
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain" and part.get_content_disposition() != "attachment":
                return part.get_content()
        for part in message.walk():
            if part.get_content_type() == "text/html" and part.get_content_disposition() != "attachment":
                return part.get_content()
        return "(Message has no printable text body.)"

    if message.get_content_maintype() == "text":
        return message.get_content()
    return "(Message has no printable text body.)"


def _print_message(raw_message):
    message = BytesParser(policy=policy.default).parsebytes(raw_message)
    print(f"From: {message.get('From', '')}")
    print(f"To: {message.get('To', '')}")
    print(f"Date: {message.get('Date', '')}")
    print(f"Subject: {message.get('Subject', '')}")
    print()
    print(_message_text(message))


def print_last_email():
    """Connect to IMAP over SSL and print the newest message in the mailbox."""
    host = os.getenv("IMAP_HOST")
    username = os.getenv("IMAP_USERNAME")
    app_password = os.getenv("IMAP_APP_PASSWORD")
    mailbox = os.getenv("IMAP_MAILBOX", "INBOX")

    missing = [
        name for name, value in (
            ("IMAP_HOST", host),
            ("IMAP_USERNAME", username),
            ("IMAP_APP_PASSWORD", app_password),
        ) if not value
    ]
    if missing:
        raise RuntimeError(f"Missing .env setting(s): {', '.join(missing)}")

    connection = imaplib.IMAP4_SSL(host)
    try:
        connection.login(username, app_password)
        status, _ = connection.select(mailbox, readonly=True)
        if status != "OK":
            raise RuntimeError(f"Could not open IMAP mailbox: {mailbox}")

        status, search_data = connection.search(None, "ALL")
        if status != "OK":
            raise RuntimeError("Could not search the IMAP mailbox")
        message_ids = search_data[0].split()
        if not message_ids:
            print(f"No email in {mailbox}.")
            return

        status, fetch_data = connection.fetch(message_ids[-1], "(RFC822)")
        if status != "OK":
            raise RuntimeError("Could not fetch the newest email")
        raw_message = next(
            (item[1] for item in fetch_data if isinstance(item, tuple)), None
        )
        if raw_message is None:
            raise RuntimeError("IMAP returned no message data")

        _print_message(raw_message)
    finally:
        try:
            connection.logout()
        except imaplib.IMAP4.error:
            pass


# re-issue IDLE well before servers (Gmail: ~29 min) or mobile/NAT networks drop a quiet connection
IDLE_SECONDS = 9 * 60
# wait between reconnect attempts, doubled after each failure up to the maximum
RECONNECT_DELAY = 5
RECONNECT_DELAY_MAX = 5 * 60


def wait_for_sender_email(sender=None):
    """Wait with IMAP IDLE and print each new message from the given sender.

    The sender defaults to IMAP_SENDER from .env.
    When the connection drops (e.g. 'socket error: EOF') it reconnects and
    also picks up messages that arrived while it was disconnected.
    """
    if not hasattr(imaplib.IMAP4, "idle"):
        raise RuntimeError("IMAP IDLE requires Python 3.14 or newer")

    host = os.getenv("IMAP_HOST")
    username = os.getenv("IMAP_USERNAME")
    app_password = os.getenv("IMAP_APP_PASSWORD")
    mailbox = os.getenv("IMAP_MAILBOX", "INBOX")
    sender = sender or os.getenv("IMAP_SENDER")
    missing = [
        name for name, value in (
            ("IMAP_HOST", host),
            ("IMAP_USERNAME", username),
            ("IMAP_APP_PASSWORD", app_password),
            ("IMAP_SENDER", sender),
        ) if not value
    ]
    if missing:
        raise RuntimeError(f"Missing .env setting(s): {', '.join(missing)}")

    # UIDs already handled; kept across reconnects so no message is printed twice
    seen_uids = None
    uid_validity = None
    delay = RECONNECT_DELAY
    print(f"Waiting for new email from {sender} in {mailbox}. Press Ctrl+C to stop.")
    try:
        while True:
            connection = None
            lost = None
            try:
                connection = imaplib.IMAP4_SSL(host)
                connection.login(username, app_password)
                status, _ = connection.select(mailbox, readonly=True)
                if status != "OK":
                    raise RuntimeError(f"Could not open IMAP mailbox: {mailbox}")

                # UIDs are only comparable while UIDVALIDITY stays the same
                current_validity = _uid_validity(connection)
                if current_validity != uid_validity:
                    seen_uids = None
                    uid_validity = current_validity

                if seen_uids is None:
                    seen_uids = _all_uids(connection)
                else:
                    # catch up on messages that arrived while disconnected
                    _print_new_from_sender(connection, sender, seen_uids)
                delay = RECONNECT_DELAY

                while True:
                    with connection.idle(duration=IDLE_SECONDS) as idler:
                        for response_type, _ in idler:
                            response_name = (
                                response_type.decode().upper()
                                if isinstance(response_type, bytes)
                                else response_type.upper()
                            )
                            if response_name in ("EXISTS", "RECENT"):
                                break
                    _print_new_from_sender(connection, sender, seen_uids)
            except (imaplib.IMAP4.abort, OSError) as e:
                # dropped connection (socket error: EOF, reset, timeout, network change)
                lost = e
            finally:
                if connection is not None:
                    try:
                        connection.logout()
                    except (imaplib.IMAP4.error, OSError):
                        pass

            if lost is not None:
                print(f"\nConnection lost ({lost}), reconnecting in {delay}s...")
                time.sleep(delay)
                delay = min(delay * 2, RECONNECT_DELAY_MAX)
    except KeyboardInterrupt:
        print("\nStopped watching for email.")


def _uid_validity(connection):
    status, data = connection.response("UIDVALIDITY")
    return data[0] if status == "UIDVALIDITY" and data and data[0] else None


def _all_uids(connection):
    status, data = connection.uid("search", None, "ALL")
    if status != "OK":
        raise RuntimeError("Could not search the IMAP mailbox")
    return {int(uid) for uid in data[0].split()}


def _print_new_from_sender(connection, sender, seen_uids):
    """Print messages from sender that are not in seen_uids, and add them to seen_uids."""
    current_uids = _all_uids(connection)
    new_uids = sorted(current_uids - seen_uids)
    seen_uids.update(current_uids)

    for uid in new_uids:
        status, fetch_data = connection.uid("fetch", str(uid), "(RFC822)")
        if status != "OK":
            continue
        raw_message = next(
            (item[1] for item in fetch_data if isinstance(item, tuple)), None
        )
        if raw_message is None:
            continue
        message = BytesParser(policy=policy.default).parsebytes(raw_message)
        from_addresses = {
            address.lower()
            for _, address in getaddresses(message.get_all("From", []))
        }
        if sender.lower() in from_addresses:
            print("\nNew matching email:")
            _print_message(raw_message)


if __name__ == "__main__":
    wait_for_sender_email()

"""Fetch and watch messages in an IMAP mailbox.

public functions:
    print_last_email()
        print the newest message in the mailbox
    watch_sender_emails(on_message, sender=None, load_position=None,
                        save_position=None, on_status=None)
        wait with IMAP IDLE and call on_message(message) for each new email
        from sender, reconnecting when the connection drops
    wait_for_sender_email(sender=None)
        watch_sender_emails() that prints each new email
    message_text(message)
        the plain-text (or html) body of an email.message.EmailMessage

.env settings:
    IMAP_HOST, IMAP_USERNAME, IMAP_APP_PASSWORD
    IMAP_MAILBOX   (optional, default INBOX)
    IMAP_SENDER    email address to watch, used when no sender is given
"""

import imaplib
import os
import time
import traceback
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses

from dotenv import load_dotenv


load_dotenv()


def message_text(message):
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


def _print_message(message):
    print(f"From: {message.get('From', '')}")
    print(f"To: {message.get('To', '')}")
    print(f"Date: {message.get('Date', '')}")
    print(f"Subject: {message.get('Subject', '')}")
    print()
    print(message_text(message))


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

        _print_message(BytesParser(policy=policy.default).parsebytes(raw_message))
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
    """
    def print_email(message):
        print("\nNew matching email:")
        _print_message(message)

    watch_sender_emails(print_email, sender)


def watch_sender_emails(on_message, sender=None, load_position=None, save_position=None, on_status=None):
    """Wait with IMAP IDLE and call on_message(message) for each new email from sender.

    sender          defaults to IMAP_SENDER from .env
    load_position() returns the saved (uid_validity, last_uid) or None
    save_position(uid_validity, last_uid)
                    called after each new email, so a restart continues after
                    the last handled email instead of skipping or repeating any
    on_status(text) called with 'connected', 'waiting' (at least every IDLE_SECONDS)
                    and 'reconnecting: <error>'

    Without a saved position only emails that arrive after the start are handled.
    When the connection drops (e.g. 'socket error: EOF') it reconnects and
    also handles emails that arrived while it was disconnected.
    Errors raised by on_message are printed and that email is skipped.
    Returns on Ctrl+C.
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

    on_status = on_status or (lambda text: None)
    # last handled UID, kept across reconnects; UIDs only grow while UIDVALIDITY stays the same
    position = {"uid_validity": None, "last_uid": None}
    saved = load_position() if load_position else None
    if saved:
        position["uid_validity"], position["last_uid"] = saved

    def handle(uid, message):
        try:
            on_message(message)
        except Exception:
            print(f"\nError while handling email {uid}, skipped:")
            traceback.print_exc()

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

                current_validity = _uid_validity(connection)
                if position["last_uid"] is None or current_validity != position["uid_validity"]:
                    # first start, or the mailbox was rebuilt: begin after the newest email
                    position["uid_validity"] = current_validity
                    position["last_uid"] = max(_all_uids(connection), default=0)
                    if save_position:
                        save_position(position["uid_validity"], position["last_uid"])
                else:
                    # catch up on emails that arrived while stopped or disconnected
                    _handle_new_from_sender(connection, sender, position, handle, save_position)
                delay = RECONNECT_DELAY
                on_status("connected")

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
                    _handle_new_from_sender(connection, sender, position, handle, save_position)
                    on_status("waiting")
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
                on_status(f"reconnecting: {lost}")
                time.sleep(delay)
                delay = min(delay * 2, RECONNECT_DELAY_MAX)
    except KeyboardInterrupt:
        print("\nStopped watching for email.")


def _uid_validity(connection):
    status, data = connection.response("UIDVALIDITY")
    if status != "UIDVALIDITY" or not data or not data[0]:
        return None
    value = data[0]
    return value.decode() if isinstance(value, bytes) else str(value)


def _all_uids(connection):
    status, data = connection.uid("search", None, "ALL")
    if status != "OK":
        raise RuntimeError("Could not search the IMAP mailbox")
    return {int(uid) for uid in data[0].split()}


def _handle_new_from_sender(connection, sender, position, handle, save_position):
    """Call handle(uid, message) for emails from sender newer than position["last_uid"]."""
    new_uids = sorted(uid for uid in _all_uids(connection) if uid > position["last_uid"])
    for uid in new_uids:
        status, fetch_data = connection.uid("fetch", str(uid), "(RFC822)")
        raw_message = next(
            (item[1] for item in fetch_data if isinstance(item, tuple)), None
        ) if status == "OK" else None
        if raw_message is None:
            print(f"\nCould not fetch email {uid}, skipped")
        else:
            message = BytesParser(policy=policy.default).parsebytes(raw_message)
            from_addresses = {
                address.lower()
                for _, address in getaddresses(message.get_all("From", []))
            }
            if sender.lower() in from_addresses:
                handle(uid, message)
        position["last_uid"] = uid
        if save_position:
            save_position(position["uid_validity"], uid)


if __name__ == "__main__":
    wait_for_sender_email()

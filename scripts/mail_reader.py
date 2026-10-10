"""Fetch and watch messages in an IMAP mailbox.

public functions:
    print_last_email()
        print the newest message in the mailbox
    watch_sender_emails(on_message, sender=None,
                        load_position=None,
                        save_position=None,
                        on_status=None)
        wait with IMAP IDLE and call on_message(message)
        for each new email from sender, reconnecting
        when the connection drops
    wait_for_sender_email(sender=None)
        watch_sender_emails() that prints each new email
    message_text(message)
        the plain-text (or html) body of an
        email.message.EmailMessage

.env settings:
    IMAP_HOST, IMAP_USERNAME, IMAP_APP_PASSWORD
    IMAP_MAILBOX  (optional, default INBOX)
    IMAP_SENDER   email address to watch, used when no
                  sender is given
"""

import imaplib
import logging
import os
import time
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses

from dotenv import load_dotenv

# .env lives in the repo root, one level above scripts/
ROOT_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
load_dotenv(os.path.join(ROOT_DIR, ".env"))

log = logging.getLogger("mail_reader")

# re-issue IDLE well before servers (Gmail: ~29 min) or
# mobile/NAT networks drop a quiet connection
IDLE_SECONDS = 9 * 60
# wait between reconnect attempts, doubled after each
# failure up to the maximum
RECONNECT_DELAY = 5
RECONNECT_DELAY_MAX = 5 * 60

NO_BODY = "(Message has no printable text body.)"


def message_text(message):
    """Return the first plain-text body, or a decoded
    fallback body."""
    if not message.is_multipart():
        if message.get_content_maintype() == "text":
            return message.get_content()
        return NO_BODY
    for content_type in ("text/plain", "text/html"):
        for part in message.walk():
            disposition = part.get_content_disposition()
            if (
                part.get_content_type() == content_type
                and disposition != "attachment"
            ):
                return part.get_content()
    return NO_BODY


def _print_message(message):
    print(f"From: {message.get('From', '')}")
    print(f"To: {message.get('To', '')}")
    print(f"Date: {message.get('Date', '')}")
    print(f"Subject: {message.get('Subject', '')}")
    print()
    print(message_text(message))


def _settings(sender=None, need_sender=False):
    """the IMAP settings from .env; raise RuntimeError
    naming the missing ones"""
    settings = {
        "host": os.getenv("IMAP_HOST"),
        "username": os.getenv("IMAP_USERNAME"),
        "app_password": os.getenv("IMAP_APP_PASSWORD"),
        "mailbox": os.getenv("IMAP_MAILBOX", "INBOX"),
        "sender": sender or os.getenv("IMAP_SENDER"),
    }
    names = {
        "IMAP_HOST": "host",
        "IMAP_USERNAME": "username",
        "IMAP_APP_PASSWORD": "app_password",
    }
    if need_sender:
        names["IMAP_SENDER"] = "sender"
    missing = [
        name
        for name, key in names.items()
        if not settings[key]
    ]
    if missing:
        raise RuntimeError(
            "Missing .env setting(s): " + ", ".join(missing)
        )
    return settings


def _connect(settings):
    """log in and open the mailbox read-only"""
    connection = imaplib.IMAP4_SSL(settings["host"])
    try:
        connection.login(
            settings["username"], settings["app_password"]
        )
        mailbox = settings["mailbox"]
        status, _ = connection.select(
            mailbox, readonly=True
        )
        if status != "OK":
            raise RuntimeError(
                f"Could not open IMAP mailbox: {mailbox}"
            )
    except BaseException:
        _logout(connection)
        raise
    return connection


def _logout(connection):
    try:
        connection.logout()
    except (imaplib.IMAP4.error, OSError):
        pass


def _parse(raw_message):
    return BytesParser(policy=policy.default).parsebytes(
        raw_message
    )


def _raw_message(fetch_data):
    """the message bytes of a FETCH (RFC822) response"""
    return next(
        (
            item[1]
            for item in fetch_data
            if isinstance(item, tuple)
        ),
        None,
    )


def print_last_email():
    """Connect to IMAP over SSL and print the newest
    message in the mailbox."""
    settings = _settings()
    connection = _connect(settings)
    try:
        status, search_data = connection.search(None, "ALL")
        if status != "OK":
            raise RuntimeError(
                "Could not search the IMAP mailbox"
            )
        message_ids = search_data[0].split()
        if not message_ids:
            print(f"No email in {settings['mailbox']}.")
            return

        status, fetch_data = connection.fetch(
            message_ids[-1], "(RFC822)"
        )
        if status != "OK":
            raise RuntimeError(
                "Could not fetch the newest email"
            )
        raw_message = _raw_message(fetch_data)
        if raw_message is None:
            raise RuntimeError(
                "IMAP returned no message data"
            )
        _print_message(_parse(raw_message))
    finally:
        _logout(connection)


def wait_for_sender_email(sender=None):
    """Wait with IMAP IDLE and print each new message
    from the given sender.

    The sender defaults to IMAP_SENDER from .env.
    """

    def print_email(message):
        print("\nNew matching email:")
        _print_message(message)

    watch_sender_emails(print_email, sender)


def watch_sender_emails(
    on_message,
    sender=None,
    load_position=None,
    save_position=None,
    on_status=None,
):
    """Wait with IMAP IDLE and call on_message(message)
    for each new email from sender.

    sender          defaults to IMAP_SENDER from .env
    load_position() returns the saved
                    (uid_validity, last_uid) or None
    save_position(uid_validity, last_uid)
                    called after each new email, so a
                    restart continues after the last
                    handled email instead of skipping
                    or repeating any
    on_status(text) called with 'connected', 'waiting'
                    (at least every IDLE_SECONDS) and
                    'reconnecting: <error>'

    Without a saved position only emails that arrive
    after the start are handled. When the connection
    drops (e.g. 'socket error: EOF') it reconnects and
    also handles emails that arrived while it was
    disconnected. Errors raised by on_message are logged
    and that email is skipped. Returns on Ctrl+C.
    """
    if not hasattr(imaplib.IMAP4, "idle"):
        raise RuntimeError(
            "IMAP IDLE requires Python 3.14 or newer"
        )
    settings = _settings(sender, need_sender=True)
    sender = settings["sender"]
    on_status = on_status or (lambda text: None)

    # last handled UID, kept across reconnects; UIDs only
    # grow while UIDVALIDITY stays the same
    position = {"uid_validity": None, "last_uid": None}
    saved = load_position() if load_position else None
    if saved:
        position["uid_validity"] = saved[0]
        position["last_uid"] = saved[1]

    def handle(uid, message):
        try:
            on_message(message)
        except Exception:
            log.exception(
                "error while handling email uid %s "
                "(subject %r), skipped",
                uid,
                message.get("Subject", ""),
            )

    def save(uid_validity, last_uid):
        if not save_position:
            return
        try:
            save_position(uid_validity, last_uid)
        except Exception:
            # not a connection problem, so don't let it
            # look like one
            log.exception(
                "could not save mail position uid %s, "
                "a restart may handle it again",
                last_uid,
            )

    def status(text):
        try:
            on_status(text)
        except Exception:
            log.exception("on_status(%r) failed", text)

    def handle_new(connection):
        _handle_new_from_sender(
            connection, sender, position, handle, save
        )

    log.info(
        "watching %s at %s for email from %s, "
        "Ctrl+C to stop",
        settings["mailbox"],
        settings["host"],
        sender,
    )
    if saved:
        log.info(
            "saved position: after email uid %s "
            "(UIDVALIDITY %s)",
            saved[1],
            saved[0],
        )
    else:
        log.info(
            "no saved position, only email arriving "
            "from now on is handled"
        )

    delay = RECONNECT_DELAY
    try:
        while True:
            connection = None
            lost = None
            try:
                log.info(
                    "connecting to %s as %s",
                    settings["host"],
                    settings["username"],
                )
                connection = _connect(settings)
                _start(
                    connection, position, save, handle_new
                )
                delay = RECONNECT_DELAY
                status("connected")
                while True:
                    reason = _wait_for_new_mail(connection)
                    log.debug(
                        "IDLE ended (%s), "
                        "checking for new email",
                        reason,
                    )
                    handle_new(connection)
                    status("waiting")
            except (imaplib.IMAP4.abort, OSError) as e:
                # dropped connection (socket error: EOF,
                # reset, timeout, network change)
                lost = e
            finally:
                if connection is not None:
                    _logout(connection)

            if lost is not None:
                log.warning(
                    "connection lost (%s: %s), "
                    "reconnecting in %ss",
                    type(lost).__name__,
                    lost,
                    delay,
                )
                status(f"reconnecting: {lost}")
                time.sleep(delay)
                delay = min(delay * 2, RECONNECT_DELAY_MAX)
    except KeyboardInterrupt:
        log.info("stopped watching for email")


def _start(connection, position, save, handle_new):
    """after connecting: begin after the newest email on
    the first start, otherwise catch up on emails that
    arrived while stopped or disconnected"""
    current_validity = _uid_validity(connection)
    if (
        position["last_uid"] is not None
        and current_validity == position["uid_validity"]
    ):
        log.info(
            "connected, catching up after email uid %s",
            position["last_uid"],
        )
        handle_new(connection)
        return

    if position["last_uid"] is not None:
        log.warning(
            "mailbox UIDVALIDITY changed %s -> %s, "
            "email in between can't be matched",
            position["uid_validity"],
            current_validity,
        )
    # first start, or the mailbox was rebuilt: begin after
    # the newest email
    position["uid_validity"] = current_validity
    position["last_uid"] = max(
        _all_uids(connection), default=0
    )
    log.info(
        "connected, starting after newest email uid %s",
        position["last_uid"],
    )
    save(position["uid_validity"], position["last_uid"])


def _wait_for_new_mail(connection):
    """IDLE until the server reports new mail or
    IDLE_SECONDS pass; return what ended it"""
    with connection.idle(duration=IDLE_SECONDS) as idler:
        for response_type, _ in idler:
            if isinstance(response_type, bytes):
                response_type = response_type.decode()
            name = response_type.upper()
            if name in ("EXISTS", "RECENT"):
                return name
    return "timeout"


def _uid_validity(connection):
    status, data = connection.response("UIDVALIDITY")
    if status != "UIDVALIDITY" or not data or not data[0]:
        return None
    value = data[0]
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def _all_uids(connection):
    status, data = connection.uid("search", None, "ALL")
    if status != "OK":
        raise RuntimeError(
            "Could not search the IMAP mailbox"
        )
    return {int(uid) for uid in data[0].split()}


def _handle_new_from_sender(
    connection, sender, position, handle, save
):
    """Call handle(uid, message) for emails from sender
    newer than position["last_uid"]."""
    new_uids = sorted(
        uid
        for uid in _all_uids(connection)
        if uid > position["last_uid"]
    )
    if new_uids:
        log.debug("new email uid(s): %s", new_uids)
    for uid in new_uids:
        status, fetch_data = connection.uid(
            "fetch", str(uid), "(RFC822)"
        )
        raw_message = None
        if status == "OK":
            raw_message = _raw_message(fetch_data)
        if raw_message is None:
            log.warning(
                "could not fetch email uid %s (%s), "
                "skipped",
                uid,
                status,
            )
        else:
            _handle_one(
                uid, _parse(raw_message), sender, handle
            )
        position["last_uid"] = uid
        save(position["uid_validity"], uid)


def _handle_one(uid, message, sender, handle):
    """pass the message to handle() if it is from sender"""
    from_addresses = {
        address.lower()
        for _, address in getaddresses(
            message.get_all("From", [])
        )
    }
    if sender.lower() not in from_addresses:
        log.debug(
            "email uid %s from %s ignored, not from %s",
            uid,
            message.get("From", ""),
            sender,
        )
        return
    log.info(
        "email uid %s from %s: %r (Message-ID %s)",
        uid,
        message.get("From", ""),
        message.get("Subject", ""),
        message.get("Message-ID", "-"),
    )
    handle(uid, message)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
    )
    wait_for_sender_email()

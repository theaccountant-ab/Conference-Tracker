"""Scan an IMAP mailbox for conference-related emails.

Point this at a dedicated mailbox (or folder) where you forward all conference
mail. On each run it pulls new messages, hands their text to the extractor, and
(optionally) marks them seen so they aren't processed again.
"""

from __future__ import annotations

import email
import imaplib
import re
from email.message import Message
from html.parser import HTMLParser
from typing import Iterator, List

from ..config import MailboxConfig
from .base import SourceDocument


class _HTMLTextExtractor(HTMLParser):
    """Minimal HTML-to-text: drop tags, keep visible text and skip script/style."""

    def __init__(self) -> None:
        super().__init__()
        self._chunks: List[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip and data.strip():
            self._chunks.append(data)

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "\n".join(self._chunks)).strip()


def _html_to_text(html: str) -> str:
    parser = _HTMLTextExtractor()
    try:
        parser.feed(html)
    except Exception:
        return html
    return parser.text()


def _decode(payload: bytes, charset: str | None) -> str:
    for enc in (charset, "utf-8", "latin-1"):
        if not enc:
            continue
        try:
            return payload.decode(enc, errors="replace")
        except (LookupError, UnicodeDecodeError):
            continue
    return payload.decode("utf-8", errors="replace")


def message_to_text(msg: Message) -> str:
    """Return the best-effort plain-text body of an email (subject + body)."""
    subject = str(email.header.make_header(email.header.decode_header(
        msg.get("Subject", "")
    )))

    plain_parts: List[str] = []
    html_parts: List[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if "attachment" in disp:
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            text = _decode(payload, part.get_content_charset())
            if ctype == "text/plain":
                plain_parts.append(text)
            elif ctype == "text/html":
                html_parts.append(_html_to_text(text))
    else:
        payload = msg.get_payload(decode=True)
        if payload is not None:
            text = _decode(payload, msg.get_content_charset())
            if msg.get_content_type() == "text/html":
                html_parts.append(_html_to_text(text))
            else:
                plain_parts.append(text)

    body = "\n\n".join(plain_parts) or "\n\n".join(html_parts)
    return (f"Subject: {subject}\n\n{body}").strip()


class EmailSource:
    """An IMAP mailbox treated as a stream of conference documents."""

    def __init__(self, config: MailboxConfig):
        self.config = config

    def _connect(self) -> imaplib.IMAP4:
        cfg = self.config
        if cfg.use_ssl:
            conn: imaplib.IMAP4 = imaplib.IMAP4_SSL(cfg.host, cfg.port)
        else:
            conn = imaplib.IMAP4(cfg.host, cfg.port)
        conn.login(cfg.username, cfg.password)
        return conn

    def _disconnect(self, conn: imaplib.IMAP4) -> None:
        for step in (conn.close, conn.logout):
            try:
                step()
            except Exception:
                # A dropped/idle socket can make teardown raise; never let that
                # mask a successful scan.
                pass

    def iter_documents(self) -> Iterator[SourceDocument]:
        cfg = self.config
        if not cfg.host or not cfg.username:
            raise RuntimeError(
                "Mailbox is not configured (set CT_MAIL_HOST / CT_MAIL_USER, "
                "etc., or fill in config.yaml)."
            )

        # Fetch every raw message up front and close the connection *before*
        # extraction. Extraction can take minutes (many LLM calls), and Gmail
        # drops idle IMAP sockets after a few minutes — so holding the
        # connection open across extraction crashes the run on teardown. We
        # reconnect briefly at the end only to mark messages read.
        # Identify and fetch messages by UID (stable across reconnects, unlike
        # sequence numbers) so we can mark them read from a fresh connection.
        conn = self._connect()
        raw_messages: List[tuple[bytes, bytes]] = []
        try:
            conn.select(cfg.folder)
            criterion = "UNSEEN" if cfg.unseen_only else "ALL"
            typ, data = conn.uid("SEARCH", None, criterion)
            if typ == "OK" and data and data[0]:
                for uid in data[0].split():
                    typ, msg_data = conn.uid("FETCH", uid, "(RFC822)")
                    if typ != "OK" or not msg_data or not msg_data[0]:
                        continue
                    raw_messages.append((uid, msg_data[0][1]))
        finally:
            self._disconnect(conn)

        processed_uids: List[bytes] = []
        try:
            for uid, raw in raw_messages:
                msg = email.message_from_bytes(raw)
                text = message_to_text(msg)
                if not text.strip():
                    continue
                origin = f"email:{msg.get('Message-ID', uid.decode())}"
                # Record the uid as processed only after the consumer signals
                # success, so a transient extraction failure leaves the message
                # unread to be retried on the next run.
                marker = {"done": False}

                def on_success(_m=marker):
                    _m["done"] = True

                yield SourceDocument(text=text, origin=origin, on_success=on_success)
                if marker["done"]:
                    processed_uids.append(uid)
        finally:
            if cfg.unseen_only and processed_uids:
                self._mark_seen(processed_uids)

    def _mark_seen(self, uids: List[bytes]) -> None:
        """Reconnect briefly and flag the given messages (by UID) as read."""
        try:
            conn = self._connect()
        except Exception:
            return
        try:
            conn.select(self.config.folder)
            for uid in uids:
                try:
                    conn.uid("STORE", uid, "+FLAGS", "\\Seen")
                except Exception:
                    pass
        finally:
            self._disconnect(conn)

from email.message import EmailMessage

from conference_tracker.config import MailboxConfig
from conference_tracker.sources import email_source, tally_source
from conference_tracker.sources.email_source import EmailSource
from conference_tracker.sources.tally_source import TallyEmailSource


def _raw(sender: str, subject: str, body: str) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["Subject"] = subject
    msg["Message-ID"] = f"<{subject.replace(' ', '-')}@x>"
    msg.set_content(body)
    return msg.as_bytes()


class FakeIMAP:
    """Just enough IMAP for the sources; FETCH RFC822 marks mail read, like Gmail."""

    def __init__(self, mailbox):
        self.mailbox = mailbox  # uid -> {"raw": bytes, "seen": bool}

    def login(self, *_):
        pass

    def select(self, _folder):
        return "OK", [b"1"]

    def close(self):
        pass

    def logout(self):
        pass

    def uid(self, command, *args):
        if command == "SEARCH":
            criteria = [a for a in args if a is not None]
            sender = None
            if "FROM" in criteria:
                sender = criteria[criteria.index("FROM") + 1].strip('"')
            uids = [u for u, m in self.mailbox.items()
                    if not ("UNSEEN" in criteria and m["seen"])
                    and (sender is None or sender.encode() in m["raw"])]
            return "OK", [b" ".join(uids)]
        if command == "FETCH":
            uid, what = args
            if "PEEK" not in what:
                self.mailbox[uid]["seen"] = True
            return "OK", [(b"", self.mailbox[uid]["raw"])]
        if command == "STORE":
            self.mailbox[args[0]]["seen"] = True
            return "OK", []
        raise AssertionError(command)


def _config():
    return MailboxConfig(host="imap.example.com", username="me", password="x")


def test_email_scan_leaves_tally_submission_unread_for_the_tally_scan(monkeypatch):
    mailbox = {
        b"1": {"raw": _raw("news@ssrn.com", "cfp", "Call for papers ..."), "seen": False},
        b"2": {"raw": _raw("Tally <notifications@tally.so>", "New submission",
                           "Conference: Test Finance Conference"), "seen": False},
    }
    fake = FakeIMAP(mailbox)
    monkeypatch.setattr(email_source.EmailSource, "_connect", lambda self: fake)
    monkeypatch.setattr(tally_source.TallyEmailSource, "_connect", lambda self: fake)

    # The daily email scan processes the newsletter and skips the Tally email.
    for doc in EmailSource(_config()).iter_documents():
        doc.on_success()
    assert mailbox[b"1"]["seen"] is True
    assert mailbox[b"2"]["seen"] is False

    docs = list(TallyEmailSource(_config()).iter_documents())
    assert [d.origin for d in docs] == ["tally:<New-submission@x>"]
    assert "Test Finance Conference" in docs[0].text


def test_tally_scan_marks_read_only_after_success(monkeypatch):
    mailbox = {
        b"7": {"raw": _raw("notifications@tally.so", "New submission", "Conference: X"),
               "seen": False},
    }
    fake = FakeIMAP(mailbox)
    monkeypatch.setattr(tally_source.TallyEmailSource, "_connect", lambda self: fake)

    # Extraction failed (e.g. daily quota): the email stays unread for the next hour.
    list(TallyEmailSource(_config()).iter_documents())
    assert mailbox[b"7"]["seen"] is False

    for doc in TallyEmailSource(_config()).iter_documents():
        doc.on_success()
    assert mailbox[b"7"]["seen"] is True

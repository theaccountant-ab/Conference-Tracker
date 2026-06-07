import os
import tempfile

from conference_tracker.models import Conference, ExtractedConference
from conference_tracker.store import CSVStore, normalize_name


def _store():
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    os.unlink(path)  # start with no file
    return CSVStore(path), path


def test_normalize_name():
    assert normalize_name("NeurIPS 2026!") == "neurips 2026"
    assert normalize_name("  ACL   2026  ") == "acl 2026"


def test_insert_then_merge():
    store, path = _store()
    try:
        c1 = Conference.from_extracted(
            ExtractedConference(
                name="ACL 2026",
                url="https://2026.aclweb.org",
                submission_deadline="2026-02-15",
            ),
            source="email:1",
        )
        added, updated = store.upsert([c1])
        assert (added, updated) == (1, 0)

        # Same conference, new location info -> merge, not duplicate.
        c2 = Conference.from_extracted(
            ExtractedConference(name="ACL 2026", location="Vienna, Austria"),
            source="email:2",
        )
        added, updated = store.upsert([c2])
        assert (added, updated) == (0, 1)

        rows = store.load()
        assert len(rows) == 1
        row = rows[0]
        assert row.location == "Vienna, Austria"
        assert row.contact == "https://2026.aclweb.org"  # preserved
        assert row.status  # status was computed on save
    finally:
        os.path.exists(path) and os.unlink(path)


def test_contact_prefers_url_over_email():
    c = Conference.from_extracted(
        ExtractedConference(
            name="X", url="https://x.org", submission_email="cfp@x.org"
        )
    )
    assert c.contact == "https://x.org"

    c2 = Conference.from_extracted(
        ExtractedConference(name="Y", submission_email="cfp@y.org")
    )
    assert c2.contact == "cfp@y.org"

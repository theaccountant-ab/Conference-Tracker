import os
import tempfile

from conference_tracker.models import Conference, ExtractedConference
from conference_tracker.store import CSVStore, normalize_contact, normalize_name


def _store():
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    os.unlink(path)
    return CSVStore(path), path


def test_normalize_name_drops_the_and_subtitle():
    assert normalize_name("The Australasian Finance and Banking Conference") == (
        "australasian finance and banking conference"
    )
    assert normalize_name('MIT GCFP Annual Conference | "Theme"') == (
        "mit gcfp annual conference"
    )


def test_normalize_contact():
    assert normalize_contact("https://www.x.org/") == "x.org"
    assert normalize_contact("mailto:cfp@x.org") == "cfp@x.org"
    assert normalize_contact("HTTP://Y.ORG/sub/") == "y.org/sub"


def test_merges_on_contact_when_name_varies():
    store, path = _store()
    try:
        a = Conference.from_extracted(
            ExtractedConference(
                name="CLIMATE FINANCE & POLICY (CFP)",
                url="https://cfp2026.sciencesconf.org/submission/submit",
                submission_deadline="2026-07-31",
            )
        )
        added, _ = store.upsert([a])
        assert added == 1

        # Same conference, different name, same submission URL -> merge.
        b = Conference.from_extracted(
            ExtractedConference(
                name="Climate Finance & Policy",
                url="https://cfp2026.sciencesconf.org/submission/submit",
                location="Bari, Italy",
            )
        )
        added, updated = store.upsert([b])
        assert (added, updated) == (0, 1)
        rows = store.load()
        assert len(rows) == 1
        assert rows[0].location == "Bari, Italy"
    finally:
        os.path.exists(path) and os.unlink(path)


def test_distinct_conferences_stay_separate():
    store, path = _store()
    try:
        store.upsert(
            [
                Conference.from_extracted(
                    ExtractedConference(name="Conf A", url="https://a.org")
                ),
                Conference.from_extracted(
                    ExtractedConference(name="Conf B", url="https://b.org")
                ),
            ]
        )
        assert len(store.load()) == 2
    finally:
        os.path.exists(path) and os.unlink(path)

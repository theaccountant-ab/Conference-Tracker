import os
import tempfile

from google.genai import errors

from conference_tracker import cli, extractor
from conference_tracker.config import Config
from conference_tracker.models import ExtractedConference
from conference_tracker.sources.base import SourceDocument
from conference_tracker.store import CSVStore


class _Quota(errors.APIError):
    def __init__(self):
        Exception.__init__(self, "429 RESOURCE_EXHAUSTED")
        self.code = 429


class _Src:
    def __init__(self, docs):
        self.docs = docs
        self.done = []

    def iter_documents(self):
        for d in self.docs:
            yield SourceDocument(text=d, origin=f"t:{d}",
                                 on_success=lambda d=d: self.done.append(d))


def test_run_source_skips_incomplete_rows_and_stops_on_quota(monkeypatch):
    calls = []

    def fake_extract(client, model, text):
        calls.append(text)
        if text == "complete":
            return [ExtractedConference(name="Good Conf", location="Boston, MA",
                                        submission_deadline="2026-12-01",
                                        start_date="2027-05-01", end_date="2027-05-02")]
        if text == "incomplete":
            return [ExtractedConference(name="No Deadline Conf", location="Paris",
                                        start_date="2027-05-01")]
        raise _Quota()

    monkeypatch.setattr(extractor, "extract_conferences", fake_extract)
    monkeypatch.setattr(cli, "_client", lambda config: None)
    d = tempfile.mkdtemp()
    cfg = Config(csv_path=os.path.join(d, "c.csv"))
    src = _Src(["complete", "incomplete", "quota", "never-reached"])
    assert cli.run_source(cfg, src) == 0

    names = [r.name for r in CSVStore(cfg.csv_path).load()]
    assert names == ["Good Conf"]                 # incomplete row not written
    assert "never-reached" not in calls           # run stopped at the quota error
    assert src.done == ["complete", "incomplete"]  # quota doc not marked done

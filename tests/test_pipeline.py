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


def test_run_source_skips_deadline_that_does_not_fit_dates(monkeypatch):
    def fake_extract(client, model, text):
        return [
            # Deadline after the conference: mixed-up years -> skipped.
            ExtractedConference(name="ESA Meeting", location="Charlottesville, VA",
                                submission_deadline="2027-08-03",
                                start_date="2026-10-29", end_date="2026-11-01"),
            ExtractedConference(name="Fine Conf", location="Boston, MA",
                                submission_deadline="2026-08-03",
                                start_date="2026-10-29", end_date="2026-11-01"),
        ]

    monkeypatch.setattr(extractor, "extract_conferences", fake_extract)
    monkeypatch.setattr(cli, "_client", lambda config: None)
    d = tempfile.mkdtemp()
    cfg = Config(csv_path=os.path.join(d, "c.csv"))
    assert cli.run_source(cfg, _Src(["doc"])) == 0
    assert [r.name for r in CSVStore(cfg.csv_path).load()] == ["Fine Conf"]


def test_describe_quota_error_names_the_limit_and_retry_time():
    from datetime import datetime, timezone

    from conference_tracker.sources.search_source import describe_quota_error

    payload = (
        "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'details': [{'violations': "
        "[{'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier', "
        "'quotaDimensions': {'model': 'gemini-2.5-flash', 'location': 'global'}, "
        "'quotaValue': '20'}]}, {'retryDelay': '24621s'}]}}"
    )
    msg = describe_quota_error(Exception(payload),
                               now=datetime(2026, 10, 8, 17, 9, 39, tzinfo=timezone.utc))
    assert msg.startswith("daily limit (GenerateRequestsPerDayPerProjectPerModel-FreeTier")
    assert "20 requests" in msg and "gemini-2.5-flash" in msg
    assert "retry in 6h50m, about 00:00 UTC" in msg

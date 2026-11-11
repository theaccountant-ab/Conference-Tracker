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


def _quota_exc(quota_id, retry="12s"):
    exc = _Quota()
    exc.args = (f"429 RESOURCE_EXHAUSTED. {{'violations': [{{'quotaId': '{quota_id}', "
                f"'quotaValue': '5'}}], 'retryDelay': '{retry}'}}",)
    return exc


def test_per_minute_limit_is_waited_out_and_retried():
    from conference_tracker.sources.search_source import call_with_retry

    calls, waits = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise _quota_exc("GenerateRequestsPerMinutePerProjectPerModel-FreeTier")
        return "ok"

    assert call_with_retry(flaky, "'X'", sleep=waits.append) == "ok"
    assert len(calls) == 3 and waits == [13.0, 13.0]  # retryDelay + 1s


def test_daily_limit_is_not_retried():
    import pytest

    from conference_tracker.sources.search_source import call_with_retry

    waits = []

    def daily():
        raise _quota_exc("GenerateRequestsPerDayPerProjectPerModel-FreeTier", "24620s")

    with pytest.raises(errors.APIError):
        call_with_retry(daily, "'X'", sleep=waits.append)
    assert waits == []


def test_google_overload_is_retried_with_backoff():
    from conference_tracker.sources.search_source import call_with_retry

    calls, waits = [], []

    def overloaded():
        calls.append(1)
        if len(calls) < 3:
            raise errors.ServerError(503, {"error": {
                "code": 503, "status": "UNAVAILABLE",
                "message": "This model is currently experiencing high demand."}})
        return "ok"

    assert call_with_retry(overloaded, "'X'", sleep=waits.append) == "ok"
    assert waits == [30.0, 60.0]


def test_lasting_overload_gives_up_after_the_last_attempt():
    import pytest

    from conference_tracker.sources.search_source import call_with_retry

    waits = []

    def down():
        raise errors.ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE"}})

    with pytest.raises(errors.APIError):
        call_with_retry(down, "'X'", sleep=waits.append)
    assert waits == [30.0, 60.0, 120.0]


def test_other_errors_are_not_retried():
    import pytest

    from conference_tracker.sources.search_source import call_with_retry

    waits = []

    def bad_request():
        raise errors.ClientError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT"}})

    with pytest.raises(errors.APIError):
        call_with_retry(bad_request, "'X'", sleep=waits.append)
    assert waits == []


def test_literal_unicode_escape_in_name_is_decoded():
    from conference_tracker.models import Conference

    c = Conference.from_extracted(ExtractedConference(
        name="Review of Accounting Studies\\u2013International Accounting Standards Board Joint Conference"))
    assert c.name == "Review of Accounting Studies–International Accounting Standards Board Joint Conference"


def test_location_escape_glitches_are_decoded_or_dropped():
    from conference_tracker.models import Conference

    def loc(raw):
        return Conference.from_extracted(ExtractedConference(name="X Conf", location=raw)).location

    assert loc("Montr\t00e9al, Canada") == "Montréal, Canada"     # mangled escape
    assert loc("Montr\\u00e9al, Canada") == "Montréal, Canada"    # literal escape
    assert loc("Z\rich, Switzerland") == ""                      # unrecoverable
    assert loc("Boston, MA") == "Boston, MA"


def test_garbled_location_never_overwrites_a_good_one():
    import os
    import tempfile

    from conference_tracker.models import Conference
    from conference_tracker.store import CSVStore

    d = tempfile.mkdtemp()
    store = CSVStore(os.path.join(d, "c.csv"))
    store.save([Conference(name="SGF Conference", location="Zürich, Switzerland",
                           submission_deadline="2026-10-31", start_date="2027-04-09",
                           end_date="2027-04-09")])
    incoming = Conference.from_extracted(ExtractedConference(
        name="SGF Conference", location="Z\rich, Switzerland",
        submission_deadline="2026-10-31", start_date="2027-04-09", end_date="2027-04-09"))
    store.upsert([incoming])
    assert store.load()[0].location == "Zürich, Switzerland"


def test_gemini_client_uses_the_v1beta_api():
    # google-genai 3.x defaults to "v1", where the system instructions every
    # extraction sends are rejected.
    from conference_tracker.cli import _client
    from conference_tracker.config import Config

    client = _client(Config(gemini_api_key="test-key"))
    assert client._api_client._http_options.api_version == "v1beta"


def _bad_request(*_):
    raise errors.ClientError(400, {"error": {
        "code": 400, "status": "INVALID_ARGUMENT",
        "message": "Developer instruction is not enabled for api version v1."}})


def test_run_source_fails_when_every_gemini_call_fails(monkeypatch):
    monkeypatch.setattr(extractor, "extract_conferences", _bad_request)
    monkeypatch.setattr(cli, "_client", lambda config: None)
    cfg = Config(csv_path=os.path.join(tempfile.mkdtemp(), "c.csv"))
    src = _Src(["a", "b"])
    assert cli.run_source(cfg, src) == 1
    assert src.done == []  # left unread, so the next run retries them


def test_run_source_succeeds_when_only_some_calls_fail(monkeypatch):
    def flaky(client, model, text):
        if text == "bad":
            _bad_request()
        return []

    monkeypatch.setattr(extractor, "extract_conferences", flaky)
    monkeypatch.setattr(cli, "_client", lambda config: None)
    cfg = Config(csv_path=os.path.join(tempfile.mkdtemp(), "c.csv"))
    assert cli.run_source(cfg, _Src(["bad", "ok"])) == 0


def test_run_source_fails_when_every_web_search_fails(monkeypatch):
    class _FailedSearch(_Src):
        def __init__(self):
            super().__init__([])
            self.failed = ["Some Conference", "Other Conference"]

    monkeypatch.setattr(cli, "_client", lambda config: None)
    cfg = Config(csv_path=os.path.join(tempfile.mkdtemp(), "c.csv"))
    assert cli.run_source(cfg, _FailedSearch()) == 1


def test_running_out_of_quota_is_not_a_failure(monkeypatch):
    def quota(*_):
        raise _Quota()

    monkeypatch.setattr(extractor, "extract_conferences", quota)
    monkeypatch.setattr(cli, "_client", lambda config: None)
    cfg = Config(csv_path=os.path.join(tempfile.mkdtemp(), "c.csv"))
    assert cli.run_source(cfg, _Src(["a"])) == 0

from datetime import date

from conference_tracker.status import (
    ENDED,
    PARTICIPATION,
    SUBMISSION,
    UNKNOWN,
    compute_status,
    parse_date,
)

TODAY = date(2026, 6, 7)


def test_submission_open():
    assert compute_status("2026-07-01", "2026-09-01", "2026-09-03", TODAY) == SUBMISSION


def test_submission_deadline_is_today_still_open():
    assert compute_status("2026-06-07", "2026-09-01", "2026-09-03", TODAY) == SUBMISSION


def test_participation_after_deadline_before_end():
    assert compute_status("2026-05-01", "2026-09-01", "2026-09-03", TODAY) == PARTICIPATION


def test_ended_after_end_date():
    assert compute_status("2026-01-01", "2026-03-01", "2026-03-03", TODAY) == ENDED


def test_end_falls_back_to_start():
    # No end date; start is in the past and deadline passed -> ended.
    assert compute_status("2026-01-01", "2026-03-01", "", TODAY) == ENDED
    # Start in the future, deadline passed -> participation.
    assert compute_status("2026-05-01", "2026-09-01", "", TODAY) == PARTICIPATION


def test_deadline_passed_no_conference_dates():
    assert compute_status("2026-05-01", "", "", TODAY) == PARTICIPATION


def test_unknown_when_no_dates():
    assert compute_status("", "", "", TODAY) == UNKNOWN


def test_ended_conference_overrides_future_deadline():
    # Stale/bad data: the event was in 2024 but a future deadline lingers.
    # An event that has already ended must not show as open for submission.
    assert compute_status("2026-09-30", "2024-12-16", "2024-12-18", TODAY) == ENDED


def test_corrupt_end_before_start_is_ignored():
    # end_date precedes start_date (wrong year) -> ignore end, use start.
    # Start is in the future and the deadline is open -> Submission, not Ended.
    assert compute_status("2026-10-31", "2027-04-09", "2023-03-31", TODAY) == SUBMISSION
    # Same corruption but no open deadline and a future start -> Participation.
    assert compute_status("", "2027-04-09", "2023-03-31", TODAY) == PARTICIPATION


def test_parse_date_variants():
    assert parse_date("2026-06-07") == date(2026, 6, 7)
    assert parse_date("2026/06/07") == date(2026, 6, 7)
    assert parse_date("2026-06-07T12:00:00") == date(2026, 6, 7)
    assert parse_date("") is None
    assert parse_date(None) is None
    assert parse_date("not a date") is None

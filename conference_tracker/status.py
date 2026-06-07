"""Derive a conference's lifecycle status from its dates.

The status is one of:

* ``Submission``    — you can still submit a paper (today <= submission deadline).
* ``Participation`` — submissions are closed but the conference hasn't ended yet
                      (you can still attend / participate).
* ``Ended``         — the conference is over.
* ``Unknown``       — not enough date information to decide.

Status is intentionally *derived*, never stored as ground truth: it depends on
today's date, so it is recomputed every time the dataset is written or refreshed.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

SUBMISSION = "Submission"
PARTICIPATION = "Participation"
ENDED = "Ended"
UNKNOWN = "Unknown"


def parse_date(value: Optional[str]) -> Optional[date]:
    """Parse an ISO-8601 date string, tolerating empty/None and full timestamps."""
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    # Accept plain dates and ISO datetimes.
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(value[: len(fmt) + 2], fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def compute_status(
    submission_deadline: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
    today: Optional[date] = None,
) -> str:
    """Return the lifecycle status for a conference given its dates.

    The "conference is over" boundary uses the end date when available, falling
    back to the start date (a single-day event, or one where only the start was
    announced).
    """
    today = today or date.today()
    deadline = parse_date(submission_deadline)
    start = parse_date(start_date)
    end = parse_date(end_date) or start

    # Still open for submissions.
    if deadline is not None and today <= deadline:
        return SUBMISSION

    # We know when it ends (or started) — decide ended vs. ongoing.
    if end is not None:
        return ENDED if today > end else PARTICIPATION

    # Deadline passed but we have no conference dates at all.
    if deadline is not None and today > deadline:
        return PARTICIPATION

    return UNKNOWN

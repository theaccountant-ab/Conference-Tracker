"""Data models for the conference tracker.

`ExtractedConference` is the structured shape we ask Claude to return when it
reads an email or web page. `Conference` is the persisted record (extraction
result + computed status + bookkeeping) that ends up as a row in the CSV.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Extraction schema (what Claude returns)
# ---------------------------------------------------------------------------
class ExtractedConference(BaseModel):
    """Fields Claude extracts from an unstructured source (email or web page).

    Every field except ``name`` is optional: real-world sources are often
    incomplete, and we'd rather store a partial record than drop it. Dates are
    returned as ISO-8601 strings (``YYYY-MM-DD``) so they sort and parse
    cleanly; ``None`` means "not stated in the source".
    """

    name: str = Field(description="Official name of the conference.")
    url: Optional[str] = Field(
        default=None,
        description="Homepage / call-for-papers URL of the conference, if any.",
    )
    submission_email: Optional[str] = Field(
        default=None,
        description=(
            "Email address for paper submission. Only set this when there is "
            "no submission website to point at."
        ),
    )
    location: Optional[str] = Field(
        default=None,
        description=(
            "Location, standardized as 'City, Country' for international "
            "conferences and 'City, State' (two-letter state) for US "
            "conferences. Use 'Online' for fully virtual events."
        ),
    )
    submission_deadline: Optional[str] = Field(
        default=None,
        description="Paper submission deadline as an ISO-8601 date (YYYY-MM-DD).",
    )
    start_date: Optional[str] = Field(
        default=None,
        description="Conference start date as an ISO-8601 date (YYYY-MM-DD).",
    )
    end_date: Optional[str] = Field(
        default=None,
        description="Conference end date as an ISO-8601 date (YYYY-MM-DD).",
    )
    is_conference: bool = Field(
        default=True,
        description=(
            "False if the source does not actually describe an academic "
            "conference / call for papers (e.g. spam, a newsletter)."
        ),
    )


# ---------------------------------------------------------------------------
# Persisted record (a row in the CSV)
# ---------------------------------------------------------------------------
# Column order for the CSV. Kept as a module constant so the store and any
# consumer agree on the schema.
CSV_FIELDS = [
    "name",
    "contact",          # URL if present, else submission email
    "location",
    "submission_deadline",
    "status",           # Submission | Participation | Ended | Unknown
    "start_date",
    "end_date",
    "last_updated",     # ISO timestamp of last write
    "source",           # where this record was last sourced from
]


@dataclass
class Conference:
    """A persisted conference record."""

    name: str
    contact: str = ""
    location: str = ""
    submission_deadline: str = ""
    status: str = ""
    start_date: str = ""
    end_date: str = ""
    last_updated: str = ""
    source: str = ""

    def to_row(self) -> dict:
        return {k: (getattr(self, k) or "") for k in CSV_FIELDS}

    @classmethod
    def from_row(cls, row: dict) -> "Conference":
        return cls(**{k: (row.get(k) or "") for k in CSV_FIELDS})

    @classmethod
    def from_extracted(
        cls, extracted: ExtractedConference, source: str = ""
    ) -> "Conference":
        contact = extracted.url or extracted.submission_email or ""
        return cls(
            name=extracted.name.strip(),
            contact=contact.strip(),
            location=(extracted.location or "").strip(),
            submission_deadline=(extracted.submission_deadline or "").strip(),
            start_date=(extracted.start_date or "").strip(),
            end_date=(extracted.end_date or "").strip(),
            source=source,
        )

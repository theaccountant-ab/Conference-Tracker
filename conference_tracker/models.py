"""Data models for the conference tracker.

`ExtractedConference` is the structured shape we ask the model to return when it
reads an email or web page. `Conference` is the persisted record (extraction
result + computed status + bookkeeping) that ends up as a row in the CSV.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional

from pydantic import BaseModel, Field


# Edition ordinals ("39th", "7th", "2nd") and standalone years ("2026"),
# optionally with a leading separator so "FEM-2026" -> "FEM" and "(CFP-2026)"
# -> "(CFP)". Stripping these keeps a recurring conference's name stable from
# one year (and edition) to the next, so it lands on the same row.
_EDITION_ORDINAL = re.compile(r"\b\d+(?:st|nd|rd|th)\b", re.IGNORECASE)
_YEAR = re.compile(r"[-–/]?\s*\b(?:19|20)\d{2}\b")
_EMPTY_OR_TRAILING_PARENS = re.compile(r"\(\s*([^()]*?)[\s\-–]*\)")


def clean_conference_name(name: str) -> str:
    """Drop edition numbers and years from a conference name.

    "The 39th Australasian Finance and Banking Conference" -> "The Australasian
    Finance and Banking Conference"; "7th Financial Economics Meeting (FEM-2026)"
    -> "Financial Economics Meeting (FEM)"; "ICBFS 2026" -> "ICBFS".
    """
    if not name:
        return ""
    s = _EDITION_ORDINAL.sub(" ", name)
    s = _YEAR.sub(" ", s)
    # Tidy parentheticals left like "(FEM )" or "(CFP- )" -> "(FEM)"/"(CFP)";
    # drop any that ended up empty.
    s = _EMPTY_OR_TRAILING_PARENS.sub(
        lambda m: f"({m.group(1).strip()})" if m.group(1).strip() else " ", s
    )
    s = re.sub(r"\s+([,)])", r"\1", s)        # no space before , or )
    s = re.sub(r"\s{2,}", " ", s)              # collapse runs of whitespace
    return s.strip(" -–,|")


# ---------------------------------------------------------------------------
# Extraction schema (what the model returns)
# ---------------------------------------------------------------------------
class ExtractedConference(BaseModel):
    """Fields the model extracts from an unstructured source (email or web page).

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


class ExtractedConferenceList(BaseModel):
    """Container the model fills in for one source document.

    A single email is often a newsletter/digest that lists *many* calls for
    papers, so extraction returns a list. An empty list means the document
    contained no academic conference (e.g. it was purely job postings or ads).
    """

    conferences: List[ExtractedConference] = Field(
        default_factory=list,
        description=(
            "Every distinct academic conference / call for papers found in the "
            "text. Empty if the text contains none."
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
            name=clean_conference_name(extracted.name.strip()),
            contact=contact.strip(),
            location=(extracted.location or "").strip(),
            submission_deadline=(extracted.submission_deadline or "").strip(),
            start_date=(extracted.start_date or "").strip(),
            end_date=(extracted.end_date or "").strip(),
            source=source,
        )

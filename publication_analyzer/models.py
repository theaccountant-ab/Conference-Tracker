"""Structured schema the model fills in when parsing research notes about a
conference's papers and where they were published."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class PaperPublication(BaseModel):
    """One paper presented at a conference and its journal-publication outcome.

    ``published_journal`` is the journal the paper later appeared in (``None``
    if it was never published in a journal, or the outcome is unknown), and
    ``is_top_tier`` records whether that journal is considered a top-tier outlet.
    """

    title: str = Field(description="Title of the paper as presented.")
    year: Optional[int] = Field(
        default=None,
        description="Calendar year the paper was presented at the conference.",
    )
    published_journal: Optional[str] = Field(
        default=None,
        description=(
            "Name of the peer-reviewed journal the paper was later published "
            "in. Null if it was not published in a journal, or the outcome "
            "could not be determined."
        ),
    )
    is_top_tier: Optional[bool] = Field(
        default=None,
        description=(
            "True if `published_journal` is a top-tier journal in the field, "
            "false if it is a journal but not top-tier, null if unpublished "
            "or unknown."
        ),
    )


class PaperPublicationList(BaseModel):
    """Container for every paper found for one conference across the years."""

    papers: List[PaperPublication] = Field(
        default_factory=list,
        description=(
            "Every distinct paper presented at the conference that could be "
            "identified, with its journal-publication outcome. Empty if none "
            "could be found."
        ),
    )

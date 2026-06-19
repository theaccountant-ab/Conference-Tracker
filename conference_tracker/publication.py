"""Estimate how many papers presented at a conference reach a top-tier journal.

For a conference, this researches the papers presented in each of the past few
years (using Gemini's built-in Google Search grounding) and, for each paper,
whether it was subsequently published in a peer-reviewed journal and whether
that journal is *top-tier*. It then reports the fraction of presented papers
that landed in a top-tier journal.

This mirrors the rest of the project's two-step shape: research with search
grounding produces free text, then a second call with a Pydantic
``response_schema`` turns that text into validated records. Because it leans on
what the web search can surface, the result is a **best-effort estimate**, not
an exhaustive bibliometric census — treat the fraction as indicative.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

from google import genai
from google.genai import errors, types

from .models import PaperPublication, PaperPublicationList

# Reused from the extractor: Gemini's free tier returns these transiently when
# briefly overloaded or rate-limited, so we retry with backoff before giving up.
_TRANSIENT_CODES = {429, 500, 502, 503, 504}

# A default, finance/economics-leaning set of top-tier journals (this project's
# conference list is finance-heavy), plus a few flagship general-science and
# machine-learning outlets. Matching is case-insensitive and substring-based
# (see `is_top_tier_journal`), so "The Journal of Finance" matches "Journal of
# Finance". Override this per-run via config (`top_tier_journals`).
DEFAULT_TOP_TIER_JOURNALS = [
    # Finance
    "Journal of Finance",
    "Journal of Financial Economics",
    "Review of Financial Studies",
    "Journal of Financial and Quantitative Analysis",
    "Review of Finance",
    # Economics
    "American Economic Review",
    "Econometrica",
    "Journal of Political Economy",
    "Quarterly Journal of Economics",
    "Review of Economic Studies",
    # Accounting
    "Journal of Accounting and Economics",
    "Journal of Accounting Research",
    "The Accounting Review",
    # Management / general science
    "Management Science",
    "Nature",
    "Science",
    # Machine learning (journal outlets)
    "Journal of Machine Learning Research",
]

_RESEARCH_PROMPT = """\
Using Google Search, research the papers that were presented at the academic \
conference "{name}" in the following year(s): {years}.

For as many of those presented papers as you can identify, determine whether \
the paper was subsequently published in a peer-reviewed academic journal, and \
if so, name the journal. Search for each paper's title together with terms like \
"published", "forthcoming", or the likely journal, and consult sources such as \
the conference program/proceedings, Google Scholar, SSRN, RePEc, and the \
authors' or journals' pages.

For every paper you find, report on its own line:
- the paper title (as presented at the conference),
- the year it was presented at this conference,
- the journal it was published in, or "not published / unknown" if you cannot \
find that it appeared in a journal.

List the actual papers — do not summarize with counts only. If you cannot find \
the program for a given year, say so for that year. Be accurate and do not \
invent papers or publication outcomes.\
"""

SYSTEM_PROMPT = """\
You turn research notes about conference papers into structured records. For \
each distinct paper mentioned, output its title, the year it was presented, the \
journal it was published in (null if it was not published in a journal or the \
outcome is unknown), and whether that journal is top-tier.

{tier_guidance}

Rules:
- One entry per distinct paper. Do not invent papers or outcomes not supported \
by the notes.
- `published_journal` is the journal name only (no volume/issue); use null when \
the notes say the paper was not published, is a working paper, or the outcome \
is unknown.
- Set `is_top_tier` to null whenever `published_journal` is null.
"""

_TIER_GUIDANCE_LIST = """\
Treat a journal as top-tier ONLY if it matches one of these (case-insensitive):
{journals}
For any other journal, set is_top_tier to false."""

_TIER_GUIDANCE_MODEL = """\
Treat a journal as top-tier if it is widely regarded as a leading, flagship \
outlet in its field (the kind of journal a top-ranked department would weight \
most heavily); otherwise set is_top_tier to false."""


@dataclass
class PublicationAnalysis:
    """The publication outcome for one conference over the analyzed years."""

    conference: str
    years: List[int]
    papers: List[PaperPublication] = field(default_factory=list)
    error: str = ""

    @property
    def total_papers(self) -> int:
        return len(self.papers)

    @property
    def published_papers(self) -> int:
        return sum(1 for p in self.papers if p.published_journal)

    @property
    def top_tier_papers(self) -> int:
        return sum(1 for p in self.papers if p.is_top_tier)

    @property
    def top_tier_fraction(self) -> Optional[float]:
        """Top-tier papers / total papers found. None when no papers found."""
        if not self.papers:
            return None
        return self.top_tier_papers / len(self.papers)


def recent_years(n: int = 3, today: Optional[date] = None) -> List[int]:
    """The ``n`` completed calendar years before this one (most recent first).

    Papers need time to clear journal review, so we look at *completed* years:
    in 2026 with ``n=3`` this is ``[2025, 2024, 2023]``.
    """
    today = today or date.today()
    return [today.year - i for i in range(1, n + 1)]


def is_top_tier_journal(journal: Optional[str], top_tier: List[str]) -> bool:
    """Case-insensitive substring match of a journal name against the list.

    Substring (rather than exact) so "The Journal of Finance" matches the
    configured "Journal of Finance"; a leading "the" or trailing punctuation in
    either string therefore doesn't break the match.
    """
    if not journal:
        return False
    j = journal.strip().lower()
    return any(t.strip().lower() in j for t in top_tier if t.strip())


def _research_papers(
    client: genai.Client,
    model: str,
    name: str,
    years: List[int],
    *,
    max_output_tokens: int,
) -> str:
    """Search the web for the conference's papers and return the gathered text."""
    years_str = ", ".join(str(y) for y in years)
    response = client.models.generate_content(
        model=model,
        contents=_RESEARCH_PROMPT.format(name=name, years=years_str),
        config=types.GenerateContentConfig(
            # Built-in Google Search grounding — Gemini issues the queries and
            # grounds its answer in the results. Note: the search tool and a
            # structured `response_schema` can't be combined in one call, which
            # is why parsing happens in a separate step below.
            tools=[types.Tool(google_search=types.GoogleSearch())],
            max_output_tokens=max_output_tokens,
        ),
    )
    return (response.text or "").strip()


def _extract_papers(
    client: genai.Client,
    model: str,
    text: str,
    *,
    top_tier: List[str],
    max_output_tokens: int,
    max_retries: int,
) -> List[PaperPublication]:
    """Parse research notes into structured ``PaperPublication`` records."""
    if not text.strip():
        return []
    if top_tier:
        guidance = _TIER_GUIDANCE_LIST.format(
            journals="\n".join(f"  - {j}" for j in top_tier)
        )
    else:
        guidance = _TIER_GUIDANCE_MODEL
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT.format(tier_guidance=guidance),
        response_mime_type="application/json",
        response_schema=PaperPublicationList,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        max_output_tokens=max_output_tokens,
    )
    contents = (
        "Extract every paper described in the following research notes.\n\n"
        "<notes>\n" + text.strip() + "\n</notes>"
    )

    delay = 2.0
    for attempt in range(max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model, contents=contents, config=config
            )
            break
        except errors.APIError as exc:
            transient = getattr(exc, "code", None) in _TRANSIENT_CODES
            if not transient or attempt == max_retries:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 30.0)

    parsed = response.parsed
    if not isinstance(parsed, PaperPublicationList):
        return []
    papers = [p for p in parsed.papers if (p.title or "").strip()]
    # When a configured journal list is given, recompute `is_top_tier`
    # deterministically from the journal name rather than trusting the model —
    # it's reproducible and keeps the answer consistent with the config.
    if top_tier:
        for p in papers:
            p.is_top_tier = is_top_tier_journal(p.published_journal, top_tier)
    return papers


def analyze_conference(
    client: genai.Client,
    model: str,
    name: str,
    *,
    years: List[int],
    top_tier: Optional[List[str]] = None,
    max_research_tokens: int = 8000,
    max_output_tokens: int = 8000,
    max_retries: int = 4,
) -> PublicationAnalysis:
    """Research one conference and summarize its top-tier publication rate.

    Network/API failures are caught and recorded on ``PublicationAnalysis.error``
    so a single bad conference doesn't abort a batch run.
    """
    top_tier = DEFAULT_TOP_TIER_JOURNALS if top_tier is None else top_tier
    analysis = PublicationAnalysis(conference=name, years=list(years))
    try:
        notes = _research_papers(
            client, model, name, years, max_output_tokens=max_research_tokens
        )
        analysis.papers = _extract_papers(
            client,
            model,
            notes,
            top_tier=top_tier,
            max_output_tokens=max_output_tokens,
            max_retries=max_retries,
        )
    except errors.APIError as exc:
        analysis.error = str(exc)
    return analysis

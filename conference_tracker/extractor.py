"""Extract structured conference details from unstructured text using Gemini.

A single source document is frequently a *newsletter/digest* (e.g. SSRN's
Financial Economics Network) that lists many calls for papers at once, so the
extractor returns a **list** of conferences. We use Google's ``google-genai``
SDK with a Pydantic ``response_schema`` so the model returns validated objects
rather than free text. Extraction runs on Gemini's free API tier.
"""

from __future__ import annotations

import time
from datetime import date
from typing import List, Optional

from google import genai
from google.genai import errors, types

from .models import ExtractedConference, ExtractedConferenceList

# Gemini's free tier occasionally returns these when briefly overloaded or
# rate-limited; they're transient, so we retry with backoff before giving up.
_TRANSIENT_CODES = {429, 500, 502, 503, 504}

SYSTEM_PROMPT = """\
You extract structured information about academic conferences and calls for \
papers from emails. These emails come from a mailbox dedicated exclusively to \
conference announcements, so assume every message is about one or more academic \
conferences / calls for papers. A single email may describe one conference or be \
a digest listing many. Extract EVERY distinct conference described — even when \
the email is short, informal, a reminder, or a forward.

Rules:
- Return one entry per conference in `conferences`. A typical email yields at \
least one. Only return an empty list if the text genuinely contains no \
recoverable conference information at all (e.g. it is empty or unreadable) — do \
NOT invent a conference in that case.
- A single email may still contain non-conference items mixed in (e.g. a job \
posting or an advertisement inside a digest). Skip those individual items, but \
still extract the real conferences around them.
- Today's date is {today}. Resolve relative dates against it and infer the year \
when only a month and day are given. Output every date as an ISO-8601 date: \
YYYY-MM-DD.
- For `name`, give the conference's standing name and OMIT the edition number \
(e.g. "39th", "13th") and the year (e.g. "2026"), so the same conference matches \
across years. Keep acronyms (e.g. "FEM", "ICBFS").
- Use the *paper submission* deadline for `submission_deadline` — not the \
notification, registration, or early-bird date.
- Standardize `location` as "City, Country" for international conferences and \
"City, State" (two-letter US state abbreviation) for US conferences. Use \
"Online" for fully virtual events. If only a venue or building is named, infer \
the city and country when you reasonably can; otherwise leave it null.
- Prefer each conference's submission/homepage URL for `url`. Only set \
`submission_email` when there is no submission website to link to.
- Never invent details. If a field is not supported by the text, leave it null.
"""


def _is_plausible(c: ExtractedConference) -> bool:
    """Reject empty or obviously corrupted entries.

    A truncated/garbled model response can occasionally yield an object whose
    `name` is actually a blob of serialized JSON. Real conference names are
    short and free of JSON punctuation, so use that to filter the junk out
    before it reaches the CSV.
    """
    name = (c.name or "").strip()
    if not name or len(name) > 200:
        return False
    if "\n" in name or any(tok in name for tok in ('{"', '":', '"}', '", "')):
        return False
    return True


def _split_text(text: str) -> List[str]:
    """Split a blob roughly in half on a paragraph (then line) boundary.

    Used to recover from output truncation: a digest with so many conferences
    that the JSON answer overflows the output-token budget is broken into
    smaller pieces that each fit.
    """
    target = len(text) // 2
    for sep in ("\n\n", "\n"):
        idx = text.rfind(sep, 0, target) or -1
        # Prefer a boundary at/after the midpoint if the earlier search failed.
        if idx <= 0:
            idx = text.find(sep, target)
        if idx > 0:
            return [text[:idx].strip(), text[idx:].strip()]
    mid = target or 1
    return [text[:mid], text[mid:]]


def _extract_once(
    client: genai.Client,
    model: str,
    text: str,
    *,
    today: date,
    max_output_tokens: int,
    max_retries: int,
) -> tuple[List[ExtractedConference], bool]:
    """Run a single extraction call. Returns (conferences, was_truncated)."""
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT.format(today=today.isoformat()),
        response_mime_type="application/json",
        response_schema=ExtractedConferenceList,
        # Structured extraction doesn't need the model's "thinking" budget;
        # turning it off is faster, cheaper, and avoids it eating into the
        # output-token budget on long digests.
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        max_output_tokens=max_output_tokens,
    )
    contents = (
        "Extract every conference described in the following text.\n\n"
        "<source>\n" + text.strip() + "\n</source>"
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

    # When the JSON answer overflows max_output_tokens the model stops with
    # finish_reason MAX_TOKENS and the partial JSON won't parse — which would
    # otherwise look identical to "no conference found". Detect it so the
    # caller can split the input and retry.
    truncated = False
    try:
        reason = response.candidates[0].finish_reason
        truncated = getattr(reason, "name", str(reason)) == "MAX_TOKENS"
    except (AttributeError, IndexError, TypeError):
        truncated = False

    parsed = response.parsed
    if not isinstance(parsed, ExtractedConferenceList):
        return [], truncated
    return [c for c in parsed.conferences if _is_plausible(c)], truncated


def extract_conferences(
    client: genai.Client,
    model: str,
    text: str,
    *,
    today: Optional[date] = None,
    max_output_tokens: int = 65536,
    max_retries: int = 4,
    _depth: int = 0,
) -> List[ExtractedConference]:
    """Extract every conference described in a blob of text.

    Returns a (possibly empty) list — empty when the text holds no conference.
    Retries transient Gemini errors (overload / rate limit) with backoff; if
    they persist, the underlying ``APIError`` is raised so the caller can leave
    the source unprocessed and try again later.

    If the answer is truncated because the document lists more conferences than
    fit in one response, the document is split in half and each part extracted
    separately, so large digests are not silently dropped.
    """
    today = today or date.today()
    if not text or not text.strip():
        return []

    conferences, truncated = _extract_once(
        client,
        model,
        text,
        today=today,
        max_output_tokens=max_output_tokens,
        max_retries=max_retries,
    )
    if not truncated:
        return conferences

    # Truncated even at the model's maximum output: split once and extract each
    # half. Cap the recursion at a single split — the free API tier allows few
    # requests per day, so we must not fan out into many calls.
    parts = _split_text(text)
    if _depth >= 1 or len(parts) < 2 or any(len(p) >= len(text) for p in parts):
        return conferences
    merged: List[ExtractedConference] = []
    for part in parts:
        merged.extend(
            extract_conferences(
                client,
                model,
                part,
                today=today,
                max_output_tokens=max_output_tokens,
                max_retries=max_retries,
                _depth=_depth + 1,
            )
        )
    return merged

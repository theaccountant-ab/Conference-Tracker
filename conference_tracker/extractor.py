"""Extract structured conference details from unstructured text using Gemini.

A single source document is frequently a *newsletter/digest* (e.g. SSRN's
Financial Economics Network) that lists many calls for papers at once, so the
extractor returns a **list** of conferences. We use Google's ``google-genai``
SDK with a Pydantic ``response_schema`` so the model returns validated objects
rather than free text. Extraction runs on Gemini's free API tier.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from google import genai
from google.genai import types

from .models import ExtractedConference, ExtractedConferenceList

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


def extract_conferences(
    client: genai.Client,
    model: str,
    text: str,
    *,
    today: Optional[date] = None,
    max_output_tokens: int = 8192,
) -> List[ExtractedConference]:
    """Extract every conference described in a blob of text.

    Returns a (possibly empty) list — empty when the text holds no conference.
    """
    today = today or date.today()
    if not text or not text.strip():
        return []

    response = client.models.generate_content(
        model=model,
        contents=(
            "Extract every conference described in the following text.\n\n"
            "<source>\n" + text.strip() + "\n</source>"
        ),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT.format(today=today.isoformat()),
            response_mime_type="application/json",
            response_schema=ExtractedConferenceList,
            # Structured extraction doesn't need the model's "thinking" budget;
            # turning it off is faster, cheaper, and avoids it eating into the
            # output-token budget on long digests.
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            max_output_tokens=max_output_tokens,
        ),
    )

    parsed = response.parsed
    if not isinstance(parsed, ExtractedConferenceList):
        return []
    # Keep only entries with an actual name.
    return [c for c in parsed.conferences if c.name and c.name.strip()]

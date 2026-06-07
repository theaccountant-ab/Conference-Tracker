"""Extract structured conference details from unstructured text using Gemini.

Uses Google's ``google-genai`` SDK with a Pydantic ``response_schema`` so the
model returns a validated ``ExtractedConference`` rather than free text we'd have
to parse ourselves. Extraction runs on Gemini's free API tier, so routine runs
cost nothing.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from google import genai
from google.genai import types

from .models import ExtractedConference

SYSTEM_PROMPT = """\
You extract structured information about academic conferences and calls for \
papers from unstructured text (emails or web pages).

Rules:
- Today's date is {today}. Resolve relative dates (e.g. "next Friday", \
"this fall") against it, and infer the year when a source gives only a month \
and day. Output every date as an ISO-8601 date: YYYY-MM-DD.
- Standardize the location as "City, Country" for international conferences and \
"City, State" (two-letter US state abbreviation) for conferences in the United \
States. Use "Online" for fully virtual events. Leave it null if unknown.
- Prefer the conference's submission/homepage URL for `url`. Only set \
`submission_email` when there is no submission website to link to.
- If the text is not actually about a conference or call for papers (spam, a \
generic newsletter, an unrelated message), set `is_conference` to false.
- Never invent details. If a field is not supported by the text, leave it null.
"""


def extract_conference(
    client: genai.Client,
    model: str,
    text: str,
    *,
    today: Optional[date] = None,
    max_output_tokens: int = 2048,
) -> Optional[ExtractedConference]:
    """Run extraction on a blob of text. Returns None if it isn't a conference."""
    today = today or date.today()
    if not text or not text.strip():
        return None

    response = client.models.generate_content(
        model=model,
        contents=(
            "Extract the conference details from the following text.\n\n"
            "<source>\n" + text.strip() + "\n</source>"
        ),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT.format(today=today.isoformat()),
            response_mime_type="application/json",
            response_schema=ExtractedConference,
            max_output_tokens=max_output_tokens,
        ),
    )

    # With a Pydantic response_schema, the SDK populates ``parsed`` with an
    # ExtractedConference instance (or None if the model returned nothing usable).
    extracted = response.parsed
    if not isinstance(extracted, ExtractedConference):
        return None
    if not extracted.is_conference or not extracted.name:
        return None
    return extracted

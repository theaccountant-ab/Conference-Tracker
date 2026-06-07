"""Extract structured conference details from unstructured text using Claude.

We use the Anthropic Python SDK's structured-output helper (``messages.parse``)
so the model returns a validated ``ExtractedConference`` object rather than free
text we'd have to parse ourselves.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import anthropic

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
    client: anthropic.Anthropic,
    model: str,
    text: str,
    *,
    today: Optional[date] = None,
    max_tokens: int = 2000,
) -> Optional[ExtractedConference]:
    """Run extraction on a blob of text. Returns None if it isn't a conference."""
    today = today or date.today()
    if not text or not text.strip():
        return None

    response = client.messages.parse(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT.format(today=today.isoformat()),
        messages=[
            {
                "role": "user",
                "content": (
                    "Extract the conference details from the following text.\n\n"
                    "<source>\n" + text.strip() + "\n</source>"
                ),
            }
        ],
        output_format=ExtractedConference,
    )

    extracted = response.parsed_output
    if extracted is None or not extracted.is_conference or not extracted.name:
        return None
    return extracted

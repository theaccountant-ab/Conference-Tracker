"""Find conferences by searching the web (the "Google search" input channel).

Give it a list of conference *names* (one per line, like the URL list) and it
uses Gemini's built-in Google Search grounding to research each one — locating
the official call-for-papers page, deadlines, location, and dates — then yields
that research as a ``SourceDocument`` for the same extractor the email and
webpage sources feed. Gemini does the searching, so no separate search-API key
is required (and it runs on the free tier).
"""

from __future__ import annotations

from typing import Iterator, List

from google import genai
from google.genai import errors, types

from .base import SourceDocument

_RESEARCH_PROMPT = """\
Research the academic conference "{name}" using Google Search and report what \
you find. I need, where available:

- the official conference name (expand acronyms if the year/edition is known),
- the call-for-papers / submission homepage URL (prefer the official site),
- the submission email address, but only if there is no submission webpage,
- the location (city and country, or city and US state),
- the paper submission deadline,
- the conference start and end dates.

Search for the most recent/upcoming edition. Quote the dates and deadlines \
exactly as the sources state them, and include the URLs you relied on. If you \
cannot find a credible source for this being a real conference, say so plainly.\
"""


def read_name_list(path: str) -> List[str]:
    """Read a newline-delimited list of conference names (ignore blanks/# comments)."""
    names: List[str] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                names.append(line)
    return names


class SearchSource:
    """Treat a list of conference names as a stream of web-research documents."""

    def __init__(
        self,
        client: genai.Client,
        model: str,
        names: List[str],
        *,
        max_tokens: int = 4000,
    ):
        self.client = client
        self.model = model
        self.names = list(names)
        self.max_tokens = max_tokens

    def _research(self, name: str) -> str:
        """Search the web for one conference name and return the gathered text."""
        response = self.client.models.generate_content(
            model=self.model,
            contents=_RESEARCH_PROMPT.format(name=name),
            config=types.GenerateContentConfig(
                # Built-in Google Search grounding — Gemini issues the queries
                # and grounds its answer in the results.
                tools=[types.Tool(google_search=types.GoogleSearch())],
                max_output_tokens=self.max_tokens,
            ),
        )
        return (response.text or "").strip()

    def iter_documents(self) -> Iterator[SourceDocument]:
        for name in self.names:
            try:
                text = self._research(name)
            except errors.APIError as exc:  # one bad name shouldn't abort the run
                print(f"  ! web search failed for {name!r}: {exc}")
                continue
            if text:
                yield SourceDocument(
                    text=f"Conference to research: {name}\n\n{text}",
                    origin=f"search:{name}",
                )

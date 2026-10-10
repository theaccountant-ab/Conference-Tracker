"""Find conferences by searching the web (the "Google search" input channel).

Give it a list of conference *names* (one per line, like the URL list) and it
uses Gemini's built-in Google Search grounding to research each one — locating
the official call-for-papers page, deadlines, location, and dates — then yields
that research as a ``SourceDocument`` for the same extractor the email and
webpage sources feed. Gemini does the searching, so no separate search-API key
is required (and it runs on the free tier).
"""

from __future__ import annotations

import csv
from typing import Dict, Iterator, List

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


def is_quota_error(exc: Exception) -> bool:
    """True if an API error means the daily/rate quota is exhausted (HTTP 429)."""
    return getattr(exc, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(exc)


def load_search_state(path: str) -> Dict[str, str]:
    """Read ``name -> last_searched (YYYY-MM-DD)`` from the search state CSV."""
    state: Dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                name = (row.get("name") or "").strip()
                if name:
                    state[name] = (row.get("last_searched") or "").strip()
    except FileNotFoundError:
        pass
    return state


def save_search_state(path: str, state: Dict[str, str]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["name", "last_searched"])
        for name in sorted(state, key=str.lower):
            writer.writerow([name, state[name]])


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
        # Names fully processed this run (filled in as documents succeed).
        self.searched: List[str] = []

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
        """Yield one research document per name.

        Each document's ``on_success`` records the name in ``self.searched``
        once it has been fully processed, so the caller can note when it was
        last searched. A quota error stops the run: every remaining call would
        fail the same way, and those names simply wait for the next run.
        """
        for name in self.names:
            try:
                text = self._research(name)
            except errors.APIError as exc:
                if is_quota_error(exc):
                    print(f"  ! quota exhausted at {name!r}; stopping this run.")
                    return
                print(f"  ! web search failed for {name!r}: {exc}")
                continue
            if not text:
                self.searched.append(name)
                continue
            yield SourceDocument(
                text=f"Conference to research: {name}\n\n{text}",
                origin=f"search:{name}",
                on_success=lambda n=name: self.searched.append(n),
            )

"""Find conferences by searching the web (the "Google search" input channel).

Give it a list of conference *names* (one per line, like the URL list) and it
uses Claude's server-side web search tool to research each one — locating the
official call-for-papers page, deadlines, location, and dates — then yields that
research as a ``SourceDocument`` for the same extractor the email and webpage
sources feed. Claude does the searching server-side, so no separate search-API
key is required.
"""

from __future__ import annotations

from typing import Iterator, List

import anthropic

from .base import SourceDocument

# The dated web-search server tool. Dynamic filtering is built in on this
# version, so results are filtered before they reach the context window.
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}

_RESEARCH_PROMPT = """\
Research the academic conference "{name}" using web search and report what you \
find. I need, where available:

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
        client: anthropic.Anthropic,
        model: str,
        names: List[str],
        *,
        max_tokens: int = 4000,
        max_searches: int = 5,
    ):
        self.client = client
        self.model = model
        self.names = list(names)
        self.max_tokens = max_tokens
        # Cap the server-side search loop so a single name can't run away.
        self.max_searches = max_searches

    def _research(self, name: str) -> str:
        """Run web search for one conference name and return the gathered text."""
        messages = [
            {"role": "user", "content": _RESEARCH_PROMPT.format(name=name)}
        ]
        response = None
        # The web-search server tool runs its own loop; on pause_turn we re-send
        # the conversation so it can resume where it left off.
        for _ in range(self.max_searches):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                tools=[WEB_SEARCH_TOOL],
                messages=messages,
            )
            if response.stop_reason != "pause_turn":
                break
            messages.append({"role": "assistant", "content": response.content})

        if response is None:
            return ""
        return "\n".join(
            block.text for block in response.content if block.type == "text"
        ).strip()

    def iter_documents(self) -> Iterator[SourceDocument]:
        for name in self.names:
            try:
                text = self._research(name)
            except anthropic.APIError as exc:  # one bad name shouldn't abort the run
                print(f"  ! web search failed for {name!r}: {exc}")
                continue
            if text:
                yield SourceDocument(
                    text=f"Conference to research: {name}\n\n{text}",
                    origin=f"search:{name}",
                )

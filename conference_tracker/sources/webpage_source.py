"""Fetch a list of conference web pages and turn them into documents.

Wired into the same extraction pipeline as the other sources: give it a list of
URLs (or a text file of URLs, one per line) and it yields the page text for the
model to extract.
"""

from __future__ import annotations

import urllib.request
from typing import Iterable, Iterator, List

from .base import SourceDocument
from .email_source import _html_to_text

_USER_AGENT = "ConferenceTracker/0.1 (+https://github.com/theaccountant-ab)"


def read_url_list(path: str) -> List[str]:
    """Read a newline-delimited list of URLs, ignoring blanks and # comments."""
    urls: List[str] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


class WebpageSource:
    def __init__(self, urls: Iterable[str], timeout: int = 30):
        self.urls = list(urls)
        self.timeout = timeout

    def _fetch(self, url: str) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            raw = resp.read().decode(charset, errors="replace")
        return _html_to_text(raw)

    def iter_documents(self) -> Iterator[SourceDocument]:
        for url in self.urls:
            try:
                text = self._fetch(url)
            except Exception as exc:  # network/HTTP errors shouldn't abort the run
                text = ""
                print(f"  ! failed to fetch {url}: {exc}")
            if text.strip():
                # Prepend the URL so the model can use it as the canonical link.
                yield SourceDocument(
                    text=f"Source URL: {url}\n\n{text}", origin=f"url:{url}"
                )

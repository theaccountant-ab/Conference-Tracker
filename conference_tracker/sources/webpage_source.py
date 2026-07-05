"""Fetch a list of conference web pages and turn them into documents.

Wired into the same extraction pipeline as the other sources: give it a list of
URLs (or a text file of URLs, one per line) and it yields the page text for the
model to extract.
"""

from __future__ import annotations

import ssl
import urllib.request
from typing import Iterable, Iterator, List

from .base import SourceDocument
from .email_source import _html_to_text

# Some university/conference sites reject non-browser user-agents with a 403,
# so present a common browser UA to be let through.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


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
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.URLError as exc:
            # Some conference sites serve expired or incomplete-chain TLS certs.
            # These are public read-only pages, so fall back to an unverified
            # context rather than dropping the conference entirely.
            if not isinstance(getattr(exc, "reason", None), ssl.SSLError):
                raise
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            resp = urllib.request.urlopen(req, timeout=self.timeout, context=ctx)
        with resp:
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

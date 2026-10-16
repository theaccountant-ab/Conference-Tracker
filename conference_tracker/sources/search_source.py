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
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Iterator, List, Optional, TypeVar

from google import genai
from google.genai import errors, types

from .base import SourceDocument

T = TypeVar("T")

_RESEARCH_PROMPT = """\
Research the academic conference "{name}" using Google Search and report what \
you find. I need, where available:

- the official conference name (expand acronyms if the year/edition is known),
- the call-for-papers / submission homepage URL: the organizer's or host \
institution's own page, never a third-party conference listing or aggregator site,
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


def _field(text: str, key: str) -> str:
    m = re.search(r"""['"]%s['"]\s*:\s*['"]?([^'",}]+)""" % re.escape(key), text)
    return m.group(1).strip() if m else ""


def quota_retry_delay(exc: Exception) -> Optional[float]:
    """Seconds to wait if a 429 is only the per-minute limit, else None.

    The free tier allows a few requests per minute as well as a daily total.
    Hitting the per-minute limit just means "slow down" (Google's suggested
    delay is seconds), so it is worth waiting; the daily limit is not.
    """
    text = str(exc)
    if "PerMinute" not in _field(text, "quotaId"):
        return None
    try:
        secs = float(_field(text, "retryDelay").rstrip("s"))
    except ValueError:
        secs = 60.0
    return min(max(secs, 1.0) + 1.0, 70.0)


def call_with_minute_retry(fn: Callable[[], T], label: str, attempts: int = 4,
                           sleep: Callable[[float], None] = time.sleep) -> T:
    """Call ``fn``; on a per-minute 429, wait as Google suggests and retry.

    Any other error, a daily-limit 429, or running out of attempts re-raises,
    so callers keep their existing handling for those.
    """
    for attempt in range(attempts):
        try:
            return fn()
        except errors.APIError as exc:
            wait = quota_retry_delay(exc) if is_quota_error(exc) else None
            if wait is None or attempt == attempts - 1:
                raise
            print(f"  ~ per-minute limit at {label}; waiting {wait:.0f}s, then retrying")
            sleep(wait)
    raise AssertionError("unreachable")


def describe_quota_error(exc: Exception, now: Optional[datetime] = None) -> str:
    """Summarize which Gemini quota a 429 hit, for the run log.

    Pulls the quota id, limit, model and Google's suggested retry delay out of
    the error payload, e.g. "daily limit (GenerateRequestsPerDayPerProjectPer
    Model-FreeTier: 20 requests, gemini-2.5-flash); retry in 6h50m, about
    00:00 UTC". Falls back to the start of the error message.
    """
    text = str(exc)
    quota_id = _field(text, "quotaId")
    if not quota_id:
        return text.splitlines()[0][:200] if text else "no details"
    kind = ("daily limit" if "PerDay" in quota_id
            else "per-minute limit" if "PerMinute" in quota_id else "quota limit")
    value, model = _field(text, "quotaValue"), _field(text, "model")
    extra = ", ".join(x for x in (f"{value} requests" if value else "", model) if x)
    summary = f"{kind} ({quota_id}: {extra})" if extra else f"{kind} ({quota_id})"
    delay = _field(text, "retryDelay").rstrip("s")
    if delay.replace(".", "", 1).isdigit():
        secs = int(float(delay))
        at = (now or datetime.now(timezone.utc)) + timedelta(seconds=secs)
        summary += f"; retry in {secs // 3600}h{secs % 3600 // 60:02d}m, about {at:%H:%M} UTC"
    return summary


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
        last searched. A per-minute limit is waited out; the daily limit stops
        the run, since every remaining call would fail the same way, and those
        names simply wait for the next run.
        """
        for name in self.names:
            try:
                text = call_with_minute_retry(lambda: self._research(name), repr(name))
            except errors.APIError as exc:
                if is_quota_error(exc):
                    print(f"  ! quota exhausted at {name!r}: {describe_quota_error(exc)}; "
                          "stopping this run.")
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

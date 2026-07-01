"""Track conference homepages and detect new editions.

Reads tracked_urls.csv (columns: name, url, last_checked), skips URLs that
were checked recently or whose conference already has a current/upcoming
edition in conferences.csv, fetches the rest, and updates last_checked on
successful extraction.
"""

from __future__ import annotations

import csv
import os
from datetime import date, timedelta
from typing import Dict, Iterator, List, Optional

from .base import SourceDocument
from .webpage_source import WebpageSource

_FIELDNAMES = ["name", "url", "last_checked"]
_RECHECK_DAYS = 14
_DEADLINE_LOOKBACK_DAYS = 5 * 30  # ~5 months


def _parse_date(s: str) -> Optional[date]:
    s = s.strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


class TrackedURLSource:
    """Fetch tracked conference homepages, skipping those with recent editions.

    Skip logic (applied per URL):
    - Checked within the last 14 days → skip entirely.
    - conferences.csv has a row matching this conference name with either a
      future start_date OR a submission_deadline within the last 5 months
      → skip fetch (the conference is already current), but update last_checked.
    """

    def __init__(
        self,
        tracked_path: str,
        conferences_path: str,
        today: Optional[date] = None,
    ):
        self.tracked_path = tracked_path
        self.conferences_path = conferences_path
        self.today = today or date.today()

    # ------------------------------------------------------------------
    # CSV helpers
    # ------------------------------------------------------------------

    def _load_tracked(self) -> List[Dict[str, str]]:
        if not os.path.exists(self.tracked_path):
            return []
        with open(self.tracked_path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows = []
            for row in reader:
                # Ensure last_checked column exists even if file predates it.
                row.setdefault("last_checked", "")
                rows.append(dict(row))
        return rows

    def _save_tracked(self, rows: List[Dict[str, str]]) -> None:
        tmp = self.tracked_path + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=_FIELDNAMES, extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, self.tracked_path)

    def _load_conferences(self) -> List[Dict[str, str]]:
        if not os.path.exists(self.conferences_path):
            return []
        with open(self.conferences_path, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    # ------------------------------------------------------------------
    # Skip logic
    # ------------------------------------------------------------------

    def _recently_checked(self, row: Dict[str, str]) -> bool:
        checked = _parse_date(row.get("last_checked", ""))
        if checked is None:
            return False
        return (self.today - checked).days < _RECHECK_DAYS

    def _has_current_edition(
        self, name: str, conf_rows: List[Dict[str, str]]
    ) -> bool:
        """Return True if conferences.csv already has a current/upcoming edition."""
        from ..store import normalize_name

        key = normalize_name(name)
        if not key:
            return False
        lookback = self.today - timedelta(days=_DEADLINE_LOOKBACK_DAYS)
        for row in conf_rows:
            if normalize_name(row.get("name", "")) != key:
                continue
            start = _parse_date(row.get("start_date", ""))
            if start and start > self.today:
                return True
            deadline = _parse_date(row.get("submission_deadline", ""))
            if deadline and lookback <= deadline <= self.today:
                return True
        return False

    # ------------------------------------------------------------------
    # Main iterator
    # ------------------------------------------------------------------

    def iter_documents(self) -> Iterator[SourceDocument]:
        rows = self._load_tracked()
        if not rows:
            print("  No entries in tracked_urls.csv.")
            return

        conf_rows = self._load_conferences()
        to_fetch: List[Dict[str, str]] = []
        n_stale = 0
        n_current = 0

        for row in rows:
            url = row.get("url", "").strip()
            if not url:
                continue
            if self._recently_checked(row):
                n_stale += 1
                continue
            name = row.get("name", "").strip()
            if self._has_current_edition(name, conf_rows):
                # Mark as checked so we don't recheck for another 14 days.
                row["last_checked"] = self.today.isoformat()
                n_current += 1
                continue
            to_fetch.append(row)

        print(
            f"  {n_stale} URL(s) checked recently, "
            f"{n_current} already have a current edition, "
            f"{len(to_fetch)} to fetch."
        )

        if not to_fetch:
            self._save_tracked(rows)
            return

        source = WebpageSource([r["url"] for r in to_fetch])
        row_by_url = {r["url"]: r for r in to_fetch}

        try:
            for doc in source.iter_documents():
                url = doc.origin[len("url:"):]
                tracked_row = row_by_url.get(url)

                def on_success(_r=tracked_row, _today=self.today):
                    if _r is not None:
                        _r["last_checked"] = _today.isoformat()

                yield SourceDocument(
                    text=doc.text, origin=doc.origin, on_success=on_success
                )
        finally:
            self._save_tracked(rows)

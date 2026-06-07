"""CSV-backed storage for conference records.

The store is the source of truth for the website. It supports an idempotent
upsert keyed on a normalized conference name, merges new (non-empty) fields into
existing rows, and recomputes the derived ``status`` column on every write.
"""

from __future__ import annotations

import csv
import os
import re
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Tuple

from .models import CSV_FIELDS, Conference
from .status import compute_status


def normalize_name(name: str) -> str:
    """Key used for dedup: lowercased, punctuation stripped, whitespace collapsed."""
    name = name.lower()
    name = re.sub(r"[^a-z0-9 ]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CSVStore:
    def __init__(self, path: str):
        self.path = path

    def load(self) -> List[Conference]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, "r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            return [Conference.from_row(row) for row in reader]

    def save(self, conferences: Iterable[Conference]) -> None:
        # Recompute status for every record at write time so the dataset is
        # always current relative to today's date.
        rows = list(conferences)
        for conf in rows:
            conf.status = compute_status(
                conf.submission_deadline, conf.start_date, conf.end_date
            )
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for conf in rows:
                writer.writerow(conf.to_row())
        os.replace(tmp, self.path)

    @staticmethod
    def _merge(existing: Conference, incoming: Conference) -> bool:
        """Merge non-empty incoming fields into existing. Returns True if changed."""
        changed = False
        for fieldname in ("contact", "location", "submission_deadline",
                          "start_date", "end_date", "source"):
            new_val = (getattr(incoming, fieldname) or "").strip()
            if new_val and new_val != getattr(existing, fieldname):
                setattr(existing, fieldname, new_val)
                changed = True
        # A better (longer) name spelling can replace a terse one, but only if
        # they normalize to the same key (guaranteed by the caller).
        if incoming.name and incoming.name != existing.name and len(
            incoming.name
        ) > len(existing.name):
            existing.name = incoming.name
            changed = True
        return changed

    def upsert(self, incoming: Iterable[Conference]) -> Tuple[int, int]:
        """Insert new conferences or merge into existing ones.

        Returns ``(added, updated)`` counts.
        """
        existing = self.load()
        index: Dict[str, Conference] = {
            normalize_name(c.name): c for c in existing
        }

        added = 0
        updated = 0
        for conf in incoming:
            key = normalize_name(conf.name)
            if not key:
                continue
            if key in index:
                if self._merge(index[key], conf):
                    index[key].last_updated = _now()
                    updated += 1
            else:
                conf.last_updated = _now()
                index[key] = conf
                existing.append(conf)
                added += 1

        self.save(existing)
        return added, updated

    def refresh_status(self) -> int:
        """Recompute status for all rows (run daily). Returns rows changed."""
        rows = self.load()
        changed = 0
        for conf in rows:
            new_status = compute_status(
                conf.submission_deadline, conf.start_date, conf.end_date
            )
            if new_status != conf.status:
                changed += 1
        self.save(rows)  # save() recomputes status anyway
        return changed

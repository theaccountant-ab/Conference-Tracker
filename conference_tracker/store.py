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
    """Key used for dedup: lowercased, punctuation stripped, whitespace collapsed.

    Also drops a trailing subtitle after a ``|`` separator and a leading "the",
    so "MIT GCFP Annual Conference | Theme" and "The MIT GCFP Annual Conference"
    both key to the same conference.

    Apostrophes (straight and curly) are deleted rather than turned into spaces,
    so "Hawai'i Accounting Research Conference" and "Hawaii Accounting Research
    Conference" normalize to the same key instead of "hawai i" vs "hawaii".
    """
    name = name.split("|", 1)[0]
    name = name.lower()
    name = re.sub(r"['‘’ʻʼ`]", "", name)  # drop apostrophes
    name = re.sub(r"[^a-z0-9 ]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    if name.startswith("the "):
        name = name[4:]
    return name


def normalize_contact(contact: str) -> str:
    """Key for matching the same conference by its URL or submission email.

    A conference's submission link / email is far more stable than its name, so
    it's a strong secondary dedup signal. Lowercase, drop scheme/`www.`/`mailto:`
    and any trailing slash so trivial variations still match.
    """
    c = (contact or "").strip().lower()
    if not c:
        return ""
    c = re.sub(r"^(https?://|mailto:)", "", c)
    c = re.sub(r"^www\.", "", c)
    return c.rstrip("/")


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
        by_name: Dict[str, Conference] = {}
        by_contact: Dict[str, Conference] = {}
        for c in existing:
            by_name.setdefault(normalize_name(c.name), c)
            ck = normalize_contact(c.contact)
            if ck:
                by_contact.setdefault(ck, c)

        added = 0
        updated = 0
        for conf in incoming:
            key = normalize_name(conf.name)
            if not key:
                continue
            # Match on the name first, then fall back to the (more stable)
            # submission URL / email so the same conference under a slightly
            # different name still merges instead of duplicating.
            ckey = normalize_contact(conf.contact)
            match = by_name.get(key) or (by_contact.get(ckey) if ckey else None)
            if match is not None:
                if self._merge(match, conf):
                    match.last_updated = _now()
                    updated += 1
                # Register any new keys this record now answers to.
                by_name.setdefault(normalize_name(match.name), match)
                if normalize_contact(match.contact):
                    by_contact.setdefault(normalize_contact(match.contact), match)
            else:
                conf.last_updated = _now()
                by_name[key] = conf
                if ckey:
                    by_contact.setdefault(ckey, conf)
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

    @staticmethod
    def _dedupe_key(conf: Conference) -> Tuple[str, str]:
        """Group key for collapsing rows: same conference AND same edition.

        Keyed on the normalized name plus the start date so a recurring
        conference keeps one row per edition (distinct dates stay distinct),
        but the *same* edition never appears twice even when the two rows carry
        different contact links (e.g. an archive import vs. the live pipeline).
        """
        return (normalize_name(conf.name), (conf.start_date or "").strip())

    @staticmethod
    def _prefer(a: Conference, b: Conference) -> Conference:
        """Pick which of two same-edition rows to keep as the primary.

        Prefer a live-pipeline row over a stale ``Book1.xlsx`` archive import,
        then a browsable http(s) link over a bare email, then the row with more
        fields filled in.
        """
        def rank(c: Conference) -> tuple:
            is_archive = 1 if c.source.startswith("import:Book1") else 0
            has_web = 0 if (c.contact or "").startswith("http") else 1
            filled = -sum(
                1
                for v in (c.contact, c.location, c.submission_deadline, c.end_date)
                if (v or "").strip()
            )
            return (is_archive, has_web, filled, -len(c.name or ""))

        return a if rank(a) <= rank(b) else b

    def dedupe(self) -> int:
        """Collapse rows that are the same conference edition. Returns rows removed.

        Two rows with the same normalized name and start date are merged into
        one: the preferred row is kept and any fields it's missing are filled
        from the other. Order is preserved by emitting each group at the
        position of its first member.
        """
        rows = self.load()
        groups: Dict[Tuple[str, str], Conference] = {}
        result: List[Conference] = []
        removed = 0
        for conf in rows:
            key = self._dedupe_key(conf)
            primary = groups.get(key)
            if primary is None:
                groups[key] = conf
                result.append(conf)
                continue
            # Same edition seen already: merge into the kept row.
            removed += 1
            winner = self._prefer(primary, conf)
            loser = conf if winner is primary else primary
            # Fill only fields the winner is missing, so we never clobber good data.
            for fieldname in ("contact", "location", "submission_deadline",
                              "start_date", "end_date", "source"):
                if not (getattr(winner, fieldname) or "").strip():
                    val = (getattr(loser, fieldname) or "").strip()
                    if val:
                        setattr(winner, fieldname, val)
            if winner is not primary:
                # Replace the primary in-place in the result list.
                result[result.index(primary)] = winner
                groups[key] = winner
        self.save(result)
        return removed

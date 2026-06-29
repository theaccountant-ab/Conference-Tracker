#!/usr/bin/env python3
"""Filter a conference watchlist down to the ones that are *due* for searching.

A conference is "due" when we don't already have an upcoming edition for it on
file — i.e. none of its rows in ``conferences.csv`` has a non-Ended status. A
conference whose next edition is already recorded needs no web search this run,
so skipping it keeps each run cheap. Names that aren't in the CSV at all (e.g.
ones you added to the watchlist by hand) are always due.

Usage:
    python scripts/due_watchlist.py watchlist.txt conferences.csv > due.txt
"""

from __future__ import annotations

import sys
from collections import defaultdict

# Run from the repo root so the package imports resolve.
from conference_tracker.sources.search_source import read_name_list
from conference_tracker.store import normalize_name
from conference_tracker.status import ENDED


def due_names(watchlist_path: str, csv_path: str) -> list[str]:
    import csv

    by_key: dict[str, list[dict]] = defaultdict(list)
    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                by_key[normalize_name(row.get("name", ""))].append(row)
    except FileNotFoundError:
        by_key = {}

    due: list[str] = []
    for name in read_name_list(watchlist_path):
        rows = by_key.get(normalize_name(name), [])
        # Have an upcoming (non-Ended) edition already? Then it isn't due.
        if any((r.get("status") or "") != ENDED for r in rows):
            continue
        due.append(name)
    return due


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    for name in due_names(argv[1], argv[2]):
        print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

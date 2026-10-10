#!/usr/bin/env python3
"""Pick which watchlist names the web-search run should research today.

A name is *covered* (skipped) when we already have an upcoming edition on file:
a non-Ended row whose name matches it, or a non-Ended row that a previous web
search for that exact name produced (``source == "search:<name>"``). The second
check matters because a watchlist name like "11th Northeastern Finance
Conference, May 5-7, 2027, Boston" is stored under a cleaner name.

Every other name is a candidate. To make sure the whole watchlist gets covered
over time (rather than the same names at the top of the file every day), the
candidates are ordered by when they were last searched — never-searched first,
then oldest — using ``search_state.csv``. Names searched within ``--skip-days``
are left out, and ``--limit`` caps how many are returned so a run fits the free
Gemini quota.

Usage:
    python scripts/due_watchlist.py watchlist.txt conferences.csv \\
        [--state search_state.csv] [--limit 8] [--skip-days 30] > due.txt
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Optional

# Make the package importable whether invoked as "python scripts/..." (which
# only puts scripts/ on sys.path) or from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conference_tracker.sources.search_source import (  # noqa: E402
    load_search_state,
    read_name_list,
)
from conference_tracker.status import ENDED  # noqa: E402
from conference_tracker.store import normalize_name  # noqa: E402


def due_names(
    watchlist_path: str,
    csv_path: str,
    state: Optional[Dict[str, str]] = None,
    limit: int = 0,
    skip_days: int = 30,
    today: Optional[date] = None,
) -> List[str]:
    today = today or date.today()
    state = state or {}

    upcoming_names = set()
    upcoming_queries = set()
    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if (row.get("status") or "") == ENDED:
                    continue
                upcoming_names.add(normalize_name(row.get("name", "")))
                src = row.get("source") or ""
                if src.startswith("search:"):
                    upcoming_queries.add(normalize_name(src[len("search:"):]))
    except FileNotFoundError:
        pass

    cutoff = (today - timedelta(days=skip_days)).isoformat()
    candidates = []
    for pos, name in enumerate(read_name_list(watchlist_path)):
        key = normalize_name(name)
        if key in upcoming_names or key in upcoming_queries:
            continue
        last = state.get(name, "")
        if last and last > cutoff:
            continue  # searched recently; let others have a turn
        # Never-searched ("") sorts first, then oldest; file order breaks ties.
        candidates.append((last, pos, name))

    candidates.sort()
    names = [name for _, _, name in candidates]
    return names[:limit] if limit else names


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("watchlist")
    ap.add_argument("csv")
    ap.add_argument("--state", default="search_state.csv")
    ap.add_argument("--limit", type=int, default=0, help="max names (0 = all)")
    ap.add_argument("--skip-days", type=int, default=30)
    args = ap.parse_args(argv)
    for name in due_names(args.watchlist, args.csv, load_search_state(args.state),
                          args.limit, args.skip_days):
        print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

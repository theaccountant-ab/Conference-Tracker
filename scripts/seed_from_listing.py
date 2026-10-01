#!/usr/bin/env python3
"""Seed conference *names* into the watchlist from an aggregator's sitemap.

Given the sitemap URL of a public conference-listing site (passed at runtime,
never hard-coded), this walks the sitemap, fetches each listing page, extracts
the conference name and — if the site publishes an editorial tier badge — its
tier, drops any excluded tier, and appends the surviving names to
``watchlist.txt`` (deduped against the existing watchlist and ``conferences.csv``).

It is deliberately source-agnostic: the specific site is a command-line
argument, so this script carries no dependency on, or reference to, any
particular aggregator. The seeded names are only *candidates* — the existing
web-search pipeline (``update-search``) researches and verifies each into
``conferences.csv``, so this cannot corrupt existing rows.

Run it on a host with open network (e.g. a CI runner). Defaults to ``--dry-run``
so the first run reports what it found (tier distribution + samples) and writes
nothing; inspect the output, then re-run without ``--dry-run`` to seed.

Usage:
    python scripts/seed_from_listing.py --sitemap-url URL --dry-run
    python scripts/seed_from_listing.py --sitemap-url URL --path-filter /c/
"""

from __future__ import annotations

import argparse
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from collections import Counter
from html import unescape
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

# Make the package importable whether invoked as "python scripts/..." (which
# only puts scripts/ on sys.path) or from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conference_tracker.sources.search_source import read_name_list  # noqa: E402
from conference_tracker.store import normalize_name  # noqa: E402

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _fetch(url: str, timeout: int = 30) -> str:
    """GET a URL as text, tolerating sites with broken TLS chains."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.URLError as exc:
        if not isinstance(getattr(exc, "reason", None), ssl.SSLError):
            raise
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
    with resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


# --- Discovery: walk the sitemap and collect listing-page URLs ---------------

def discover_pages(sitemap_url: str, path_filter: str) -> List[str]:
    """Follow the sitemap (and any nested sitemaps); return pages matching filter."""
    seen: Set[str] = set()
    pages: Set[str] = set()
    stack = [sitemap_url]
    while stack:
        sm = stack.pop()
        if sm in seen:
            continue
        seen.add(sm)
        try:
            xml = _fetch(sm)
        except Exception as exc:
            print(f"  ! sitemap fetch failed {sm}: {exc}", file=sys.stderr)
            continue
        for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml):
            loc = unescape(loc.strip())
            if loc.endswith(".xml"):
                stack.append(loc)
            elif path_filter in urlparse(loc).path:
                pages.add(loc.split("#", 1)[0].split("?", 1)[0])
    print(f"Discovered {len(pages)} listing pages (filter {path_filter!r}).")
    return sorted(pages)


# --- Per-page parsing: name + optional tier ---------------------------------

_TITLE_SUFFIXES = [
    r"\s*[—–-]\s*Deadline.*$",   # "— Deadline, Dates & Location"
    r"\s*\|.*$",                  # trailing " | Site Name"
]
_TITLE_PREFIXES = [
    r"^\s*Call for Papers(?: for| :|:)?\s*",
    r"^\s*Call For Papers\s*[–—-]?\s*",
]


def _extract_title(html: str) -> str:
    m = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html, re.I)
    if not m:
        m = re.search(r'<meta[^>]+content="([^"]+)"[^>]+property="og:title"', html, re.I)
    if not m:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    return unescape(m.group(1)).strip() if m else ""


def _clean_name(title: str) -> str:
    name = title
    for pat in _TITLE_SUFFIXES:
        name = re.sub(pat, "", name, flags=re.I)
    for pat in _TITLE_PREFIXES:
        name = re.sub(pat, "", name, flags=re.I)
    name = re.sub(r"\s*\((?:19|20)\d{2}\)\s*$", "", name)  # trailing "(2027)"
    name = re.sub(r"^[\s–—:-]+", "", name)  # leftover leading dash/colon
    return re.sub(r"\s+", " ", name).strip()


def _detect_tier(html: str) -> Optional[str]:
    """Return '1'/'2'/'3'/'unranked' for the page's tier badge, else None.

    Prefers explicit badge markup (class/data-attr/aria-label/title naming the
    tier). Falls back to the first tier token near the top of the visible body
    (badges render near the top; any methodology glossary sits in the footer).
    """
    m = re.search(r'(?:class|data-tier|aria-label|title)="[^"]*tier[^"a-z]*([123])\b',
                  html, re.I)
    if m:
        return m.group(1)
    if re.search(r'(?:class|data-tier|aria-label|title)="[^"]*unranked', html, re.I):
        return "unranked"

    body = re.sub(r"(?is)<(script|style|footer)[^>]*>.*?</\1>", " ", html)
    text = unescape(re.sub(r"(?s)<[^>]+>", " ", body))
    head = text[:2500]  # badges appear near the top of the page
    m = re.search(r"\bTier\s*([123])\b", head)
    if m:
        return m.group(1)
    if re.search(r"\bUnranked\b", head):
        return "unranked"
    return None


def parse_page(url: str) -> Tuple[str, Optional[str]]:
    html = _fetch(url)
    return _clean_name(_extract_title(html)), _detect_tier(html)


# --- Main -------------------------------------------------------------------

def _existing_keys(watchlist: str, csv_path: str) -> Set[str]:
    keys: Set[str] = set()
    try:
        for n in read_name_list(watchlist):
            keys.add(normalize_name(n))
    except FileNotFoundError:
        pass
    try:
        import csv as _csv
        with open(csv_path, "r", encoding="utf-8", newline="") as fh:
            for row in _csv.DictReader(fh):
                keys.add(normalize_name(row.get("name", "")))
    except FileNotFoundError:
        pass
    return keys


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sitemap-url", required=True, help="sitemap URL of the listing site")
    ap.add_argument("--path-filter", default="/c/", help="only pages whose path contains this")
    ap.add_argument("--exclude-tier", default="3", help="tier to drop ('' to keep all)")
    ap.add_argument("--exclude-unranked", action="store_true", help="also drop Unranked venues")
    ap.add_argument("--out", default="watchlist.txt", help="watchlist to append to")
    ap.add_argument("--csv", default="conferences.csv", help="CSV to dedup against")
    ap.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    ap.add_argument("--limit", type=int, default=0, help="cap pages parsed (testing)")
    args = ap.parse_args(argv)

    pages = discover_pages(args.sitemap_url, args.path_filter)
    if args.limit:
        pages = pages[: args.limit]
    if not pages:
        print("No listing pages discovered — aborting.", file=sys.stderr)
        return 1

    existing = _existing_keys(args.out, args.csv)
    tier_counts: Counter = Counter()
    kept: Dict[str, str] = {}
    dropped = 0
    samples: List[str] = []
    failures = 0

    for url in pages:
        try:
            name, tier = parse_page(url)
        except Exception as exc:
            failures += 1
            if failures <= 15:
                print(f"  ! parse failed {url}: {exc}", file=sys.stderr)
            continue
        tier_counts[tier or "unknown"] += 1
        if len(samples) < 25:
            samples.append(f"    [{tier or '?':>8}] {name}  <{url}>")
        if not name:
            continue
        if args.exclude_tier and tier == args.exclude_tier:
            dropped += 1
            continue
        if tier == "unranked" and args.exclude_unranked:
            dropped += 1
            continue
        key = normalize_name(name)
        if not key or key in existing or key in kept:
            continue
        kept[key] = name

    print("\n=== harvest summary ===")
    print(f"Pages parsed:       {sum(tier_counts.values())} (failures: {failures})")
    print(f"Tier distribution:  {dict(tier_counts)}")
    print(f"Dropped (excluded): {dropped}")
    print(f"New names to seed:   {len(kept)} (not already tracked)")
    print("\nSample parses (tier | name | url):")
    print("\n".join(samples))

    if args.dry_run:
        print("\n[dry-run] Nothing written. Re-run without --dry-run to append.")
        return 0
    if not kept:
        print("\nNothing new to add.")
        return 0

    with open(args.out, "a", encoding="utf-8") as fh:
        fh.write("\n# --- seeded from aggregator sitemap ---\n")
        for name in sorted(kept.values(), key=str.lower):
            fh.write(name + "\n")
    print(f"\nAppended {len(kept)} names to {args.out}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""Pull approved CFP submissions from a published Google Sheet into submissions/.

Part of the hybrid "Submit your CFP" flow. A Tally form logs each submission to
a Google Sheet (one row per submission, including a link to the uploaded file).
You add an "Approved" column and tick it for the ones to publish. This script —
run on a schedule by .github/workflows/submissions.yml — reads the sheet's
published CSV, downloads each *approved, not-yet-processed* file into the
submissions/ directory, and records what it has handled so it never re-downloads.

The actual extraction/publishing is then done by `update-submissions`.

Usage:
    python scripts/fetch_submissions.py <published-csv-url> [submissions_dir]

Env overrides for the sheet's columns (all optional — auto-detected otherwise):
    CT_SHEET_APPROVED_COL   header of the approval column (default: "Approved")
    CT_SHEET_FILE_COL       header of the file-link column
    CT_SHEET_ID_COL         header of a stable per-submission id column
    CT_SHEET_NAME_COL       header used to name the file (e.g. "Conference name")
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
import urllib.request
from typing import Dict, List, Optional

_TRUE = {"true", "yes", "y", "x", "1", "✓", "checked", "approved", "done"}
_URL_RE = re.compile(r"https?://\S+")
_NAME_HINTS = ("conference", "name", "title")
_FILE_HINTS = ("file", "upload", "cfp", "paper", "pdf", "call")
_ID_HINTS = ("submission id", "respondent id", "id")


def _truthy(v: str) -> bool:
    return (v or "").strip().lower() in _TRUE


def _first_url(v: str) -> Optional[str]:
    m = _URL_RE.search(v or "")
    return m.group(0).rstrip(",;") if m else None


def _detect(headers: List[str], rows: List[Dict[str, str]], hints, *,
            prefer_urls=False) -> Optional[str]:
    low = {h: h.lower() for h in headers}
    for h in headers:  # name hint match first
        if any(hint in low[h] for hint in hints):
            return h
    if prefer_urls and rows:  # else the column most full of URLs
        best, score = None, 0
        for h in headers:
            n = sum(1 for r in rows if _first_url(r.get(h, "")))
            if n > score:
                best, score = h, n
        return best
    return None


def due_submissions(
    csv_text: str,
    processed_ids: set,
    *,
    approved_col: Optional[str] = None,
    file_col: Optional[str] = None,
    id_col: Optional[str] = None,
    name_col: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Return approved, not-yet-processed rows as {id, name, url} dicts."""
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = [ {(k or "").strip(): (v or "") for k, v in r.items()} for r in reader ]
    if not rows:
        return []
    headers = [h for h in (reader.fieldnames or []) if h]

    approved_col = approved_col or _detect(headers, rows, ("approve",)) or "Approved"
    file_col = file_col or _detect(headers, rows, _FILE_HINTS, prefer_urls=True)
    id_col = id_col or _detect(headers, rows, _ID_HINTS)
    name_col = name_col or _detect(headers, rows, _NAME_HINTS)

    out: List[Dict[str, str]] = []
    for r in rows:
        if approved_col not in r or not _truthy(r.get(approved_col, "")):
            continue
        url = _first_url(r.get(file_col, "")) if file_col else None
        if not url:
            continue
        sid = (r.get(id_col, "").strip() if id_col else "") or url
        if sid in processed_ids:
            continue
        name = (r.get(name_col, "").strip() if name_col else "") or "cfp"
        out.append({"id": sid, "name": name, "url": url})
    return out


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()[:60] or "cfp"


def _download(url: str, name: str, dest_dir: str) -> Optional[str]:
    req = urllib.request.Request(url, headers={"User-Agent": "ConferenceTracker/0.1"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
        disp = resp.headers.get("Content-Disposition", "")
    m = re.search(r'filename="?([^"]+)"?', disp)
    fname = m.group(1) if m else os.path.basename(url.split("?")[0])
    ext = os.path.splitext(fname)[1].lower() or ".pdf"
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, f"{_slug(name)}{ext}")
    i = 1
    while os.path.exists(path):
        path = os.path.join(dest_dir, f"{_slug(name)}-{i}{ext}")
        i += 1
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    csv_url = argv[1]
    submissions_dir = argv[2] if len(argv) > 2 else "submissions"
    state_path = os.path.join(submissions_dir, ".processed.json")

    processed = set()
    if os.path.exists(state_path):
        try:
            processed = set(json.load(open(state_path)))
        except Exception:
            processed = set()

    req = urllib.request.Request(csv_url, headers={"User-Agent": "ConferenceTracker/0.1"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        csv_text = resp.read().decode("utf-8", errors="replace")

    due = due_submissions(
        csv_text, processed,
        approved_col=os.environ.get("CT_SHEET_APPROVED_COL") or None,
        file_col=os.environ.get("CT_SHEET_FILE_COL") or None,
        id_col=os.environ.get("CT_SHEET_ID_COL") or None,
        name_col=os.environ.get("CT_SHEET_NAME_COL") or None,
    )
    print(f"{len(due)} approved submission(s) to fetch.")
    for d in due:
        try:
            path = _download(d["url"], d["name"], submissions_dir)
            print(f"  downloaded {d['name']!r} -> {path}")
            processed.add(d["id"])
        except Exception as exc:
            print(f"  ! failed to download {d['url']}: {exc}")

    os.makedirs(submissions_dir, exist_ok=True)
    json.dump(sorted(processed), open(state_path, "w"), indent=0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

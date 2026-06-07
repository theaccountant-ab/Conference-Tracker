"""Command-line interface for the conference tracker.

Commands:
    update-email       Scan the configured mailbox and upsert any conferences found.
    update-urls FILE   Fetch each URL in FILE and upsert any conferences found.
    update-search FILE Web-search each conference name in FILE and upsert results.
    refresh-status     Recompute the Submission/Participation/Ended status column.
    list               Print the current dataset to the terminal.
"""

from __future__ import annotations

import argparse
import sys
from typing import List

from .config import Config, load_config
from .models import Conference
from .sources.base import Source
from .store import CSVStore


def _client(config: Config):
    from google import genai

    if not config.gemini_api_key:
        # The SDK also reads GEMINI_API_KEY / GOOGLE_API_KEY from the environment.
        return genai.Client()
    return genai.Client(api_key=config.gemini_api_key)


def run_source(config: Config, source: Source) -> int:
    """Extract conferences from a source and upsert them into the CSV store.

    Returns a process exit code (0 on success).
    """
    from google.genai import errors

    from .extractor import extract_conferences

    client = _client(config)
    store = CSVStore(config.csv_path)

    found: List[Conference] = []
    n_docs = 0
    for doc in source.iter_documents():
        n_docs += 1
        try:
            # A single document (especially a newsletter) can hold many.
            extracted = extract_conferences(client, config.model, doc.text)
        except errors.APIError as exc:
            # Leave the document unprocessed (e.g. email stays unread) so the
            # next run retries it instead of silently dropping it.
            print(f"  ! extraction failed for {doc.origin}: {exc}")
            continue
        # Processed successfully — let the source finalize (mark email read).
        if doc.on_success is not None:
            doc.on_success()
        if not extracted:
            print(f"  - {doc.origin}: no conference found")
            continue
        for item in extracted:
            conf = Conference.from_extracted(item, source=doc.origin)
            print(f"  + {doc.origin}: {conf.name}")
            found.append(conf)

    added, updated = store.upsert(found)
    print(
        f"\nProcessed {n_docs} document(s): "
        f"{added} added, {updated} updated, {len(found)} conference(s) extracted."
    )
    return 0


def cmd_update_email(config: Config, args: argparse.Namespace) -> int:
    from .sources.email_source import EmailSource

    print(f"Scanning mailbox {config.mailbox.host} / {config.mailbox.folder} ...")
    return run_source(config, EmailSource(config.mailbox))


def cmd_debug_email(config: Config, args: argparse.Namespace) -> int:
    """Print the *structure* of each mailbox message and what the extractor

    makes of it, to diagnose "no conference found" cases. Deliberately prints
    no subjects or bodies — only content types, text lengths, attachment types,
    and the names of any conferences extracted — so it is safe to run in
    (potentially public) CI logs.
    """
    import email
    import imaplib

    from .extractor import extract_conferences
    from .sources.email_source import _decode, _html_to_text, message_to_text

    cfg = config.mailbox
    print(f"Diagnosing mailbox {cfg.host} / {cfg.folder} ...")
    conn: imaplib.IMAP4 = (
        imaplib.IMAP4_SSL(cfg.host, cfg.port)
        if cfg.use_ssl
        else imaplib.IMAP4(cfg.host, cfg.port)
    )
    conn.login(cfg.username, cfg.password)
    client = _client(config)
    try:
        conn.select(cfg.folder)
        typ, data = conn.search(None, "ALL")
        ids = data[0].split() if typ == "OK" and data and data[0] else []
        print(f"{len(ids)} message(s) in folder.\n")
        for i, mid in enumerate(ids, 1):
            typ, md = conn.fetch(mid, "(RFC822)")
            if typ != "OK" or not md or not md[0]:
                continue
            msg = email.message_from_bytes(md[0][1])
            types_present: List[str] = []
            attach_types: List[str] = []
            plain_len = html_len = 0
            if msg.is_multipart():
                for part in msg.walk():
                    ct = part.get_content_type()
                    if "attachment" in str(part.get("Content-Disposition", "")):
                        attach_types.append(ct)
                        continue
                    payload = part.get_payload(decode=True)
                    if payload is None:
                        continue
                    types_present.append(ct)
                    text = _decode(payload, part.get_content_charset())
                    if ct == "text/plain":
                        plain_len += len(text)
                    elif ct == "text/html":
                        html_len += len(_html_to_text(text))
            else:
                ct = msg.get_content_type()
                types_present.append(ct)
                payload = msg.get_payload(decode=True)
                if payload is not None:
                    text = _decode(payload, msg.get_content_charset())
                    if ct == "text/html":
                        html_len = len(_html_to_text(text))
                    else:
                        plain_len = len(text)
            full = message_to_text(msg)
            extracted = extract_conferences(client, config.model, full)
            names = "; ".join(c.name for c in extracted) if extracted else "(none)"
            print(
                f"[#{i}] types={sorted(set(types_present))} "
                f"attach={sorted(set(attach_types))} "
                f"plain={plain_len} html_text={html_len} total_text={len(full)} "
                f"-> {len(extracted)} extracted: {names}"
            )
    finally:
        try:
            conn.close()
        except Exception:
            pass
        conn.logout()
    return 0


def cmd_update_urls(config: Config, args: argparse.Namespace) -> int:
    from .sources.webpage_source import WebpageSource, read_url_list

    urls = read_url_list(args.file)
    print(f"Fetching {len(urls)} URL(s) ...")
    return run_source(config, WebpageSource(urls))


def cmd_update_search(config: Config, args: argparse.Namespace) -> int:
    from .sources.search_source import SearchSource, read_name_list

    names = read_name_list(args.file)
    print(f"Web-searching {len(names)} conference name(s) ...")
    client = _client(config)
    return run_source(config, SearchSource(client, config.model, names))


def cmd_refresh_status(config: Config, args: argparse.Namespace) -> int:
    store = CSVStore(config.csv_path)
    changed = store.refresh_status()
    print(f"Refreshed status for {config.csv_path}: {changed} row(s) changed.")
    return 0


def cmd_build_site(config: Config, args: argparse.Namespace) -> int:
    import os

    from .site import render_html

    store = CSVStore(config.csv_path)
    rows = store.load()
    html = render_html(rows)
    out = args.output
    parent = os.path.dirname(out)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"Wrote {out} ({len(rows)} conference(s)).")
    return 0


def cmd_list(config: Config, args: argparse.Namespace) -> int:
    store = CSVStore(config.csv_path)
    rows = store.load()
    if not rows:
        print("(no conferences yet)")
        return 0
    for conf in rows:
        print(
            f"[{conf.status or '?':<13}] {conf.name}\n"
            f"    {conf.location or '—'} | deadline: {conf.submission_deadline or '—'} "
            f"| {conf.start_date or '—'} → {conf.end_date or '—'}\n"
            f"    {conf.contact or '—'}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="conference-tracker",
        description="Automatically pull and maintain conference listings.",
    )
    parser.add_argument(
        "-c", "--config", default=None, help="Path to a YAML config file."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("update-email", help="Scan the mailbox for new conferences.")
    sub.add_parser(
        "debug-email", help="Report mailbox message structure + extraction results."
    )

    p_urls = sub.add_parser("update-urls", help="Fetch a list of conference URLs.")
    p_urls.add_argument("file", help="Text file with one URL per line.")

    p_search = sub.add_parser(
        "update-search", help="Web-search a list of conference names."
    )
    p_search.add_argument("file", help="Text file with one conference name per line.")

    sub.add_parser("refresh-status", help="Recompute the status column.")

    p_site = sub.add_parser("build-site", help="Render the HTML page for the website.")
    p_site.add_argument(
        "output", nargs="?", default="docs/index.html",
        help="Output HTML path (default: docs/index.html).",
    )

    sub.add_parser("list", help="Print the current dataset.")
    return parser


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config)

    handlers = {
        "update-email": cmd_update_email,
        "debug-email": cmd_debug_email,
        "build-site": cmd_build_site,
        "update-urls": cmd_update_urls,
        "update-search": cmd_update_search,
        "refresh-status": cmd_refresh_status,
        "list": cmd_list,
    }
    handler = handlers[args.command]
    return handler(config, args)


if __name__ == "__main__":
    sys.exit(main())

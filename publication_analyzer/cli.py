"""Command-line interface for the publication analyzer.

    analyze FILE   Estimate, for each conference name in FILE, the fraction of
                   its recently-presented papers that reached a top-tier journal.
"""

from __future__ import annotations

import argparse
import csv
import sys
from typing import List

from .analysis import analyze_conference, read_name_list, recent_years
from .config import Config, load_config


def _client(config: Config):
    from google import genai

    if not config.gemini_api_key:
        # The SDK also reads GEMINI_API_KEY / GOOGLE_API_KEY from the environment.
        return genai.Client()
    return genai.Client(api_key=config.gemini_api_key)


def cmd_analyze(config: Config, args: argparse.Namespace) -> int:
    names = read_name_list(args.file)
    years = recent_years(args.years)
    top_tier = config.top_tier_journals or None  # None -> module default list
    print(
        f"Analyzing {len(names)} conference(s) across years "
        f"{', '.join(str(y) for y in years)} ...\n"
    )
    client = _client(config)

    analyses = []
    tot_papers = tot_top = 0
    for name in names:
        analysis = analyze_conference(
            client, config.model, name, years=years, top_tier=top_tier
        )
        analyses.append(analysis)
        if analysis.error:
            print(f"  ! {name}: analysis failed: {analysis.error}")
            continue
        frac = analysis.top_tier_fraction
        frac_str = "n/a (no papers found)" if frac is None else f"{frac:.1%}"
        print(
            f"  {name}: {analysis.top_tier_papers}/{analysis.total_papers} "
            f"papers in a top-tier journal ({frac_str}); "
            f"{analysis.published_papers} published in any journal."
        )
        tot_papers += analysis.total_papers
        tot_top += analysis.top_tier_papers

    overall = (tot_top / tot_papers) if tot_papers else None
    overall_str = "n/a" if overall is None else f"{overall:.1%}"
    print(
        f"\nOverall: {tot_top}/{tot_papers} papers across all conferences "
        f"reached a top-tier journal ({overall_str})."
    )
    print(
        "Note: this is a best-effort estimate based on what a web search can "
        "surface, not an exhaustive census."
    )

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(
                ["conference", "years", "total_papers", "published_papers",
                 "top_tier_papers", "top_tier_fraction", "error"]
            )
            for a in analyses:
                frac = a.top_tier_fraction
                writer.writerow([
                    a.conference,
                    " ".join(str(y) for y in a.years),
                    a.total_papers,
                    a.published_papers,
                    a.top_tier_papers,
                    "" if frac is None else f"{frac:.4f}",
                    a.error,
                ])
        print(f"\nWrote per-conference results to {args.output}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="publication-analyzer",
        description=(
            "Estimate the fraction of a conference's recently-presented papers "
            "that were later published in a top-tier journal."
        ),
    )
    parser.add_argument(
        "-c", "--config", default=None, help="Path to a YAML config file."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "analyze",
        help="Estimate each conference's top-tier journal publication rate.",
    )
    p.add_argument("file", help="Text file with one conference name per line.")
    p.add_argument(
        "--years", type=int, default=3,
        help="Number of completed years to look back over (default: 3).",
    )
    p.add_argument(
        "--output", default=None,
        help="Optional CSV path to write per-conference results to.",
    )
    return parser


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config)

    handlers = {"analyze": cmd_analyze}
    handler = handlers[args.command]
    return handler(config, args)


if __name__ == "__main__":
    sys.exit(main())

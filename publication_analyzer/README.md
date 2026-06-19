# Publication Analyzer

A standalone tool that answers one question: **of the papers presented at a
conference over the past few years, what fraction were later published in a
top-tier journal?** It's a rough quality signal for a conference.

It lives in the same repository as the Conference Tracker but is **completely
separate** — it shares no code with the `conference_tracker` package and never
touches `conferences.csv`. It only depends on the same libraries (`google-genai`,
`PyYAML`, already in the repo's `requirements.txt`).

## How it works

For each conference name in the input file it:

1. uses Gemini's Google Search grounding to find the papers presented in each of
   the past N completed years (default 3, e.g. 2023–2025 in 2026) and where each
   was subsequently published, then
2. parses that research into structured records and counts how many landed in a
   top-tier journal.

```
conference names ─► research (Gemini + Google Search) ─► parse (Gemini, structured) ─► counts + fraction
```

This is the same two-step shape the tracker uses, but reimplemented here so the
tool stands alone.

## Use

```bash
# One conference name per line (blank lines and # comments ignored).
python -m publication_analyzer analyze conferences.txt

# Look back over a different number of years and write a per-conference CSV.
python -m publication_analyzer analyze conferences.txt --years 3 --output rates.csv
```

It prints a per-conference rate and an overall rate. With `--output` it writes a
CSV with `total_papers`, `published_papers`, `top_tier_papers`, and
`top_tier_fraction` per conference.

## Configure

Set your Gemini API key in the environment (`GEMINI_API_KEY` or `GOOGLE_API_KEY`).
Everything else is optional and can go in a YAML file passed with `-c`:

```yaml
model: gemini-2.5-flash

# Journals counted as "top-tier". Matching is case-insensitive and
# substring-based, so "Journal of Finance" matches "The Journal of Finance".
# Omit the key to use a finance/economics-leaning default list; set it empty
# to let the model judge by reputation instead.
top_tier_journals:
  - Journal of Finance
  - Journal of Financial Economics
  - Review of Financial Studies
  - American Economic Review
  - Econometrica
```

When `top_tier_journals` is set, the top-tier flag is computed deterministically
from the journal name (reproducible); otherwise the model judges by reputation.

> **Caveat:** the result is a *best-effort estimate*. It depends on what a web
> search can surface about a conference's program and each paper's eventual
> publication, so it under-counts papers it can't find and should be read as
> indicative, not as an exhaustive bibliometric census.

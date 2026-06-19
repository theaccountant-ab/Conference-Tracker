# Conference Tracker

Automatically pull and maintain a list of academic conferences for a website.
The tool reads unstructured sources — a dedicated **email** mailbox, a list of
**web pages**, or a **web search** by conference name — uses **Google Gemini**
(free API tier) to extract structured fields, and keeps a deduplicated
`conferences.csv` up to date.

For each conference it populates:

| Field | Notes |
|-------|-------|
| **name** | Official conference name |
| **contact** | Conference webpage URL, or the submission email if there's no page |
| **location** | Standardized: `City, Country` (international) or `City, State` (US); `Online` for virtual |
| **submission_deadline** | ISO date (`YYYY-MM-DD`) |
| **status** | Derived: `Submission` → `Participation` → `Ended` (or `Unknown`) |
| **start_date** / **end_date** | ISO dates |

Plus `last_updated` and `source` for bookkeeping.

### Status logic

Status is **derived from the dates** and recomputed on every run (it depends on
today's date):

- `Submission` — today is on or before the submission deadline.
- `Participation` — the deadline has passed but the conference hasn't ended yet.
- `Ended` — the end date (or start date, if no end date) is in the past.
- `Unknown` — not enough date information to decide.

## Install

```bash
pip install -r requirements.txt
```

## Configure

Copy `.env.example` to `.env` (or `config.example.yaml` to `config.yaml`) and
fill in your Gemini API key and mailbox details. Environment variables override
the YAML file. **Secrets belong in `.env`, never in the committed YAML.**

Get a free Gemini API key at [aistudio.google.com](https://aistudio.google.com/app/apikey)
and set it as `GEMINI_API_KEY`. For Gmail, create an
[App Password](https://support.google.com/accounts/answer/185833) and forward
all conference-related mail into a dedicated mailbox or label.

## Use

```bash
# Scan the mailbox for new conferences and upsert them into conferences.csv
python -m conference_tracker update-email

# Extract from a list of conference web pages (one URL per line)
python -m conference_tracker update-urls urls.txt

# Search the web for a list of conference names (one per line) and upsert them
python -m conference_tracker update-search conferences.txt

# Estimate, for each conference, the fraction of its recently presented papers
# that ended up in a top-tier journal (looks back over the past 3 years)
python -m conference_tracker analyze-publications conferences.txt
python -m conference_tracker analyze-publications conferences.txt --years 3 --output rates.csv

# Recompute the Submission/Participation/Ended column (run daily)
python -m conference_tracker refresh-status

# Print the current dataset
python -m conference_tracker list
```

## Publication-rate analysis

`analyze-publications` answers a different question from the tracker: **of the
papers presented at a conference over the past few years, what fraction were
later published in a top-tier journal?** It's a rough quality signal for a
conference.

For each conference name in the input file it:

1. uses Gemini's Google Search grounding to find the papers presented in each
   of the past N completed years (default 3, e.g. 2023–2025 in 2026) and where
   each was subsequently published, then
2. parses that research into structured records and counts how many landed in a
   top-tier journal.

It prints a per-conference rate and an overall rate, and with `--output` writes
a per-conference CSV (`total_papers`, `published_papers`, `top_tier_papers`,
`top_tier_fraction`).

**What counts as "top-tier"** is configurable via `top_tier_journals` in the
config file (a list of journal names; matching is case-insensitive and
substring-based, so `Journal of Finance` matches `The Journal of Finance`).
When that list is set, the top-tier flag is computed deterministically from the
journal name. Leave it empty to let the model judge by reputation instead. The
built-in default is a finance/economics-leaning list (see
`publication.DEFAULT_TOP_TIER_JOURNALS`).

> **Caveat:** the result is a *best-effort estimate*. It depends on what a web
> search can surface about a conference's program and each paper's eventual
> publication, so it under-counts papers it can't find and should be read as
> indicative, not as an exhaustive bibliometric census.

## Automate

`.github/workflows/update.yml` runs `update-email` + `refresh-status` daily on
GitHub's servers (where IMAP works) and commits changes to `conferences.csv`.
Add these repository secrets: `GEMINI_API_KEY`, `CT_MAIL_HOST`, `CT_MAIL_PORT`,
`CT_MAIL_USER`, `CT_MAIL_PASSWORD`, `CT_MAIL_FOLDER`.

## How it works

```
sources (email / webpages / web search)  ─►  extractor (Gemini, structured output)  ─►  CSV store (dedup + merge)
```

- **`sources/`** — each source yields `SourceDocument`s (text + provenance).
  Three are implemented: `email_source` (IMAP mailbox), `webpage_source` (a list
  of URLs), and `search_source` (Gemini's Google Search grounding, given a list
  of conference names). Adding another source means implementing one method.
- **`extractor.py`** — calls Gemini with a Pydantic `response_schema`, so the
  model returns validated fields and resolves relative dates against today.
- **`store.py`** — upserts by a normalized conference name, merges in new
  details without creating duplicates, and recomputes status on write.

## Develop

```bash
pip install -r requirements-dev.txt
pytest
```

The date/status logic and the CSV store are covered by tests that don't hit the
network or the API.

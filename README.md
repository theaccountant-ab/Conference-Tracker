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

# Recompute the Submission/Participation/Ended column (run daily)
python -m conference_tracker refresh-status

# Print the current dataset
python -m conference_tracker list
```

## Automate

`.github/workflows/update.yml` runs `update-email` + `refresh-status` daily on
GitHub's servers (where IMAP works) and commits changes to `conferences.csv`.
Add these repository secrets: `GEMINI_API_KEY`, `CT_MAIL_HOST`, `CT_MAIL_PORT`,
`CT_MAIL_USER`, `CT_MAIL_PASSWORD`, `CT_MAIL_FOLDER`.

`.github/workflows/update-search.yml` is a **separate** pipeline that researches
a curated list of conference names (`watchlist.txt`) with the web-search source
and upserts the results — a replacement for the SSRN announcement emails (being
retired end of 2026). It runs **weekly** (and on demand). Each run first narrows
the watchlist to the conferences that are *due* — those without an upcoming
edition already on file (`scripts/due_watchlist.py`) — and searches only those,
so most weeks it searches a small subset. The watchlist is every conference seen
since 2021; edit `watchlist.txt` to add or drop names. It shares only
`conferences.csv` with the email job and merges (never deletes), so the existing
setup is unaffected. Only `GEMINI_API_KEY` is needed. (Trigger it manually with
`all=true` to research the whole list.)

### Submit-your-CFP (organizer submissions)

Organizers can submit their own call for papers, so you catch conferences the
search/email sources miss. It's **approve-first**:

1. A "Submit your CFP" button on the site (shown when `submission_url` /
   `CT_SUBMISSION_URL` is set) opens a form — e.g. a free [Tally](https://tally.so)
   form with a PDF/Word file-upload field. In GitHub Actions, set the form URL as
   a repository **variable** named `CT_SUBMISSION_URL` so every rebuild keeps the
   button.
2. You review each submission, then **commit the approved CFP file into
   `submissions/`** — that commit is the approval.
3. `.github/workflows/submissions.yml` runs `update-submissions`: it extracts the
   file (PDF/Word/text) with the same Gemini extractor, publishes the file under
   `docs/cfps/` (so it becomes the conference's durable link), adds/updates the
   row, removes the file from `submissions/`, and rebuilds the page.

Run it locally with `python -m conference_tracker update-submissions`.

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

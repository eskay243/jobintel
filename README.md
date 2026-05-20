# JobIntel

Personal job-digest aggregator. Fetches listings from multiple free job boards, filters by industry vertical and region, deduplicates across sources, and emails you a daily HTML digest of new matches.

## What it does

1. **Fetches** from 6 free sources — Remotive, ArbeitNow, Adzuna (optional), The Muse, Remote OK, Jobicy
2. **Filters** by vertical: AI/ML, SaaS, FinTech, HealthTech (configurable via `filters.toml`)
3. **Filters** by region: remote, UK, US, EU, Canada (configurable)
4. **Deduplicates** using a fingerprint of normalised title + company stored in SQLite
5. **Emails** an HTML digest via SMTP (Gmail-compatible), or prints to stdout

## Prerequisites

- Python 3.11+
- A Gmail account with an [App Password](https://support.google.com/accounts/answer/185833) (or any SMTP server)
- Optional: free [Adzuna API key](https://developer.adzuna.com/) for UK/US/Canada coverage

## Installation

```bash
git clone <repo-url> && cd jobintel
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e .
```

## Configuration

Copy the template and fill in your credentials:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `SMTP_USER` | Yes | Your Gmail address |
| `SMTP_PASSWORD` | Yes | Gmail App Password |
| `MAIL_TO` | No | Recipient (defaults to SMTP_USER) |
| `ADZUNA_APP_ID` | No | Adzuna API key ID |
| `ADZUNA_APP_KEY` | No | Adzuna API key |
| `ADZUNA_ENABLED` | No | `true`/`false` (default: true if keys present) |
| `THEMUSE_ENABLED` | No | `true`/`false` (default: true) |
| `REMOTEOK_ENABLED` | No | `true`/`false` (default: true) |
| `JOBICY_COUNT` | No | Jobs to fetch from Jobicy (max 50, default 50) |
| `LOG_LEVEL` | No | `DEBUG`/`INFO`/`WARNING` (default: INFO) |

## Usage

```bash
# Fetch, filter, dedupe, email new jobs
python -m jobintel run

# Dry-run: print new matches without saving or emailing
python -m jobintel run --dry-run

# Save but skip email
python -m jobintel run --no-email

# Only show remote + US jobs
python -m jobintel run --regions remote us

# Show jobs from all regions (vertical filter still applies)
python -m jobintel run --all-regions

# Show how many unique roles are tracked
python -m jobintel stats
```

## Cron schedule (3× daily)

```cron
0 7,12,18 * * *  cd /path/to/project && .venv/bin/python -m jobintel run
```

## Customising filters

Edit `filters.toml` in the project root (created automatically if absent — defaults are embedded in code).

**Add a new vertical:**

```toml
[verticals.devops]
patterns = [
    "\\bdevops\\b",
    "platform engineering",
    "\\bsre\\b",
    "site reliability",
    "kubernetes",
    "\\bk8s\\b",
]
```

**Tighten or expand a region:**

```toml
[regions.uk]
patterns = [
    "\\buk\\b",
    "united kingdom",
    "london",
    "manchester",
    "edinburgh",
    "my-new-city",
]
```

Changes take effect on the next run — no code change needed.

## Adding a new source

1. Create `jobintel/sources/<name>.py` with a `fetch_<name>(client)` function returning `list[Job]`.
2. Import it in `jobintel/sources/__init__.py` and append to the list in `all_fetchers()`.

## Project structure

```
jobintel/
├── __main__.py       CLI entry point (run, stats)
├── config.py         Environment variable loading + validation
├── models.py         Job dataclass with fingerprint()
├── filters.py        Vertical + region matching (reads filters.toml)
├── dedupe.py         Title/company normalisation, URL hashing
├── storage.py        SQLite dedup store (JobStore)
├── emailer.py        HTML + plain-text SMTP digest
├── http_utils.py     retry_get() with exponential backoff
└── sources/
    ├── remotive.py   remotive.com (remote-first)
    ├── arbeitnow.py  arbeitnow.com (Europe, paginated)
    ├── adzuna.py     Adzuna API: UK/US/CA (paginated, optional)
    ├── themuse.py    themuse.com (US tech, paginated)
    ├── remoteok.py   remoteok.com (remote-only)
    └── jobicy.py     jobicy.com (remote-only)
filters.toml          Configurable vertical + region patterns
data/jobintel.sqlite  SQLite dedup database (gitignored)
```

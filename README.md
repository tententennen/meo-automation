# MEO Automation

Fully-automated Google Business Profile (MEO) tool for:

- **THE BODY 大阪 心斎橋店**
- **THE BODY 京都店**
- **MYBEAR STUDIO 京都店**

Runs daily (unattended) to:
1. AI-generate and publish a 最新情報 local post per store, with a photo pulled from Google Drive.
2. Fetch unreplied reviews, AI-generate replies, and post them.

---

## Project layout

```
meo-automation/
├── config/
│   ├── stores.yaml        # store names, location IDs, Drive folder IDs
│   └── content.yaml       # tone, language, banned words, LLM model, cadence
├── src/meo/
│   ├── auth.py            # Google OAuth2 refresh-token flow
│   ├── business_profile.py# GBP API client (local posts + reviews)
│   ├── config.py          # YAML config loader
│   ├── content.py         # AI post/reply generator (LLM abstraction)
│   ├── drive.py           # Google Drive image fetcher
│   ├── main.py            # Unattended entrypoint — runs all 3 stores
│   ├── posts.py           # 最新情報 post feature
│   └── reviews.py         # Review reply feature
├── tests/                 # pytest suite — fully mocked, no credentials needed
├── logs/                  # Runtime log files (gitignored)
├── requirements.txt
└── pyproject.toml
```

---

## Environment Variables

All secrets come from environment variables — **never** committed to the repo.

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_CLIENT_ID` | Yes | OAuth 2.0 client ID (Desktop type) from Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | Yes | OAuth 2.0 client secret |
| `GOOGLE_REFRESH_TOKEN` | Yes | Refresh token (obtained once via `python -m meo.auth`) |
| `ANTHROPIC_API_KEY` | Yes | Anthropic Claude API key — https://console.anthropic.com/ |
| `SLACK_WEBHOOK_URL` | No | Slack incoming webhook URL for run-completion notifications |

For **development**, copy `.env.example` to `.env` (gitignored) and fill in your values:
```bash
cp .env.example .env
```
For **production** (cron/GitHub Actions/Docker), set them as system/CI environment variables.

`SLACK_WEBHOOK_URL` is optional — if unset, no notification is sent.
Create an incoming webhook at https://api.slack.com/messaging/webhooks and add the
URL as a GitHub Actions secret named `SLACK_WEBHOOK_URL` to receive a Slack message
after each daily run.

---

## Setup (first time)

### 1. Install dependencies

```bash
pip install -e ".[dev]"
# or without editable install:
pip install -r requirements.txt
```

### 2. Google Cloud project & OAuth

See **PROGRESS.md § Needs Human Action** for step-by-step instructions.

### 3. Fill in config/stores.yaml

Replace every `TODO` placeholder with the real location ID and Drive folder ID for each store.

### 4. Run

```bash
# Dry run (no API writes)
python -m meo.main --dry-run

# Live run
python -m meo.main

# Skip posts, only reply to reviews
python -m meo.main --skip-posts

# Skip reviews, only post
python -m meo.main --skip-reviews
```

---

## Running tests

```bash
pytest
```

No API credentials required — all Google and LLM calls are mocked.

---

## Customising content

Edit `config/content.yaml`:

- **`industry_tones`** — adjust tone and theme suggestions per industry.
- **`banned_words`** — words that must never appear in generated content.
- **`llm.model_id`** — swap the Claude model without code changes.
- **`defaults.post_cadence_days`** — how often to post (used by a scheduler; main.py itself runs once per invocation).

---

## Scheduling (daily unattended run)

### GitHub Actions (included)

`.github/workflows/daily_run.yml` runs automatically at 0 UTC (9 AM JST).
Add secrets in **Settings → Secrets → Actions** — see PROGRESS.md § Needs Human Action.

### cron on a VPS (Python)

```cron
# Runs at 9 AM JST (0 UTC) — adjust to your local timezone
0 0 * * * cd /path/to/meo-automation && /path/to/venv/bin/python -m meo.main >> logs/cron.log 2>&1
```

### Docker (self-hosted, recommended for VPS)

```bash
# 1. Fill in credentials
cp .env.example .env && nano .env

# 2. Build image
docker compose build

# 3. Dry run (safe — reads config, logs intent, no API writes)
docker compose run --rm meo

# 4. Live run
docker compose run --rm meo python -m meo.main

# 5. Schedule with cron on the host
# 0 0 * * * cd /path/to/meo-automation && docker compose run --rm --no-deps meo python -m meo.main >> /var/log/meo-cron.log 2>&1
```

State (`logs/state.json`) is stored in the `meo_logs` Docker named volume and persists across container restarts.

---

## Operator CLI tools

| Command | Purpose |
|---|---|
| `meo-run` | Run the full automation (posts + review replies) |
| `meo-status` | Show config/env readiness summary |
| `meo-health` | Read-only API connectivity check per store |
| `meo-validate` | Validate config files without running |
| `meo-preview` | Generate sample post/reply text via LLM (no Google API needed) |
| `meo-report` | Print recent post and reply history from state.json |
| `meo-export posts` | Export post history to CSV (for Excel / Google Sheets) |
| `meo-export replies` | Export review-reply history to CSV |
| `meo-export held-reviews` | Export reviews held for manual reply to CSV (set when `min_star_autoreply > 1`) |
| `meo-export score-history` | Export the daily health-grade snapshots (saved by `meo-score`) to CSV — one row per date × store, newest first; suitable for trend analysis in Excel or Google Sheets |
| `meo-reset` | Reset state for one store or all stores (post guard, image/theme history, reply history) |
| `meo-discover-locations` | List all GBP accounts and locations — prints ready-to-paste `location_id` values for `config/stores.yaml` (run once after API access is granted) |
| `meo-stats` | Show aggregate statistics — total posts/replies, activity rates, theme frequency, and star-rating distribution across the full archive |
| `meo-weekly-digest` | Build and send a 7-day Slack summary of posts and review replies across all stores; `--dry-run` prints to stdout without sending |
| `meo-monthly-digest` | Build and send a previous-month Slack summary (theme breakdown + full star distribution); fires automatically on the 1st of each month via `monthly_digest.yml`; `--dry-run` prints to stdout without sending |
| `meo-photo-audit` | Audit Drive photo inventory per store — shows recently-used images (offline, no credentials) or full folder contents with fresh/used breakdown and low-photo warnings (add `--live` for Drive API query) |
| `meo-review-alert` | Check for reviews held for manual reply and send an urgent Slack alert; exits 0 when none pending, exits 1 when held reviews exist (also runs automatically after each daily CI job) |
| `meo-trend` | Show period-over-period deltas (post count, reply count, average star rating) comparing this week vs last week or this month vs last month; reads state.json only — no Google credentials required |
| `meo-config-show` | Display the effective (merged) configuration for each store — combines global content.yaml defaults with per-store overrides, annotating overridden fields; no Google credentials required |
| `meo-held-reply-draft` | Generate AI reply drafts for currently held (low-star) reviews so the owner can copy-paste them into GBP; requires LLM API key but no Google credentials; exits 1 if any LLM error occurs |
| `meo-calendar` | Show a day-by-day posting calendar for all stores over the last N days (default 30), grouped in weekly chunks with posting-rate percentage and an explicit list of any missed days; reads state.json only — no Google credentials required |
| `meo-score` | Per-store health scorecard — grades each store S/A/B/C/D across posting rate (7-day), held-review count, average star rating (30-day), and Drive configuration; emits a prioritised action-item list; exits 0 when all stores are grade B or better, exits 1 otherwise; reads state.json and config only — no Google credentials required; `--slack` posts the scorecard to SLACK_WEBHOOK_URL (also added as a step in `daily_run.yml`) |
| `meo-score-history` | Daily health-grade trend table — shows the overall grade per store for the last N complete days (default 14) in a compact table format; snapshots are saved automatically by `meo-score` on each full (unfiltered) run; no Google credentials required |
| `meo-next` | Forward-looking run preview — shows for each store whether the next 09:00 JST scheduled run will post or skip (with reason), whether the Drive folder is configured, and how many reviews are held for manual reply; `--date YYYY-MM-DD` to simulate a specific run date; no Google credentials required |

```bash
# Check what the next scheduled run will do (no credentials needed)
meo-next
meo-next --store the_body_kyoto           # single store
meo-next --date 2026-08-08                # simulate a specific run date

# Discover location IDs (run once after GBP API access is approved)
meo-discover-locations

# Export examples
meo-export posts --output posts.csv
meo-export replies --store the_body_kyoto --output kyoto_replies.csv
meo-export held-reviews --output held.csv   # reviews awaiting manual reply
meo-export score-history --output grades.csv  # health-grade trends for Excel / Sheets

# Stats (once the tool has been running)
meo-stats                               # all stores
meo-stats --store the_body_kyoto        # single store

# Weekly digest (sent automatically every Monday via weekly_digest.yml)
meo-weekly-digest --dry-run             # preview without sending to Slack
meo-weekly-digest                       # send to Slack (SLACK_WEBHOOK_URL required)

# Monthly digest (sent automatically on the 1st of each month via monthly_digest.yml)
meo-monthly-digest --dry-run            # preview previous month without sending to Slack
meo-monthly-digest                      # send to Slack (SLACK_WEBHOOK_URL required)

# Photo audit (check Drive photo inventory)
meo-photo-audit                         # offline: shows recent image IDs from state.json (no credentials)
meo-photo-audit --live                  # live: queries Drive for folder contents + fresh/used breakdown
meo-photo-audit --live --store the_body_kyoto  # single-store live audit

# Review alert (check for held reviews and alert via Slack)
meo-review-alert                        # alert if held reviews exist (exits 1), silent if none (exits 0)
meo-review-alert --dry-run              # print alert to stdout, skip Slack
meo-review-alert --store the_body_kyoto # check one store

# Trend report (period-over-period comparison, no credentials needed)
meo-trend                               # this week vs last week (default)
meo-trend --period monthly              # this month vs last month
meo-trend --store the_body_kyoto        # single store

# Config show (effective merged settings per store, no credentials needed)
meo-config-show                         # all stores
meo-config-show --store the_body_kyoto  # single store (shows overrides annotated)

# Held reply draft (generate AI drafts for low-star held reviews, no Google credentials needed)
meo-held-reply-draft                    # all stores with held reviews
meo-held-reply-draft --store the_body_kyoto              # single store
meo-held-reply-draft --output logs/held_drafts.txt       # also save to file

# Posting calendar (day-by-day post history per store, no credentials needed)
meo-calendar                            # last 30 days, all stores
meo-calendar --days 7                   # last 7 days
meo-calendar --store the_body_kyoto     # single store
meo-calendar --output logs/calendar.txt # also save to file

meo-score                               # all stores (exit 0 = healthy, exit 1 = action needed)
meo-score --store the_body_kyoto        # single store
meo-score --slack                       # also post scorecard to Slack (SLACK_WEBHOOK_URL)

meo-score-history                       # last 14 days, all stores (grade trend table)
meo-score-history --days 30             # last 30 days
meo-score-history --store the_body_kyoto  # single store column
meo-score-history --output logs/score_history.txt  # also save to file

# Reset examples (use when re-testing or after manual interventions)
meo-reset post-guard --store the_body_kyoto  # allow a new post today for one store
meo-reset all                                 # clear all state for all stores
```

---

## Security

- `.gitignore` blocks all `*.json`, `.env`, and `secrets/` from being committed.
- Credentials flow only through environment variables.
- The tool never stores tokens to disk — all tokens are held in memory for the process lifetime.

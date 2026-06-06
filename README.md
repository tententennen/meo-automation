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

```bash
# Examples
meo-export posts --output posts.csv
meo-export replies --store the_body_kyoto --output kyoto_replies.csv
```

---

## Security

- `.gitignore` blocks all `*.json`, `.env`, and `secrets/` from being committed.
- Credentials flow only through environment variables.
- The tool never stores tokens to disk — all tokens are held in memory for the process lifetime.

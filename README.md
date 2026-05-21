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

| Variable | Description |
|---|---|
| `GOOGLE_CLIENT_ID` | OAuth 2.0 client ID (Desktop type) from Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | OAuth 2.0 client secret |
| `GOOGLE_REFRESH_TOKEN` | Refresh token (obtained once via `python -m meo.auth`) |
| `ANTHROPIC_API_KEY` | Anthropic Claude API key — https://console.anthropic.com/ |

For **development**, create a `.env` file (gitignored) with these values.
For **production** (cron/GitHub Actions), set them as system/CI environment variables.

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

**cron** (Linux/macOS):
```cron
0 9 * * * cd /path/to/meo-automation && /path/to/venv/bin/python -m meo.main >> logs/cron.log 2>&1
```

**GitHub Actions**: add a workflow with `schedule: - cron: '0 0 * * *'` and store env vars as repository secrets.

---

## Security

- `.gitignore` blocks all `*.json`, `.env`, and `secrets/` from being committed.
- Credentials flow only through environment variables.
- The tool never stores tokens to disk — all tokens are held in memory for the process lifetime.

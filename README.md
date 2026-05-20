# MEO Automation

Fully-automated Google Business Profile (MEO) tool for three stores:

| Key | Store |
|-----|-------|
| `the_body_osaka_shinsaibashi` | THE BODY 大阪 心斎橋店 |
| `the_body_kyoto` | THE BODY 京都店 |
| `mybear_studio_kyoto` | MYBEAR STUDIO 京都店 |

What it does (when complete):
- Generates and posts 最新情報 (local posts) to Google Business Profile daily
- Attaches a photo pulled from each store's Google Drive folder
- Fetches new/unreplied reviews, generates replies via AI, posts them

---

## Required environment variables

Copy `.env.example` to `.env` and fill in every value. **Never commit `.env`.**

| Variable | Description |
|----------|--------------|
| `GOOGLE_CLIENT_ID` | OAuth 2.0 client ID from Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | OAuth 2.0 client secret |
| `GOOGLE_REFRESH_TOKEN` | Offline refresh token (see setup guide below) |
| `LLM_API_KEY` | API key for the LLM provider (default: Anthropic Claude) |

---

## Setup

### 1. Python environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# or: pip install -e ".[dev]"
```

### 2. Google Cloud project (one-time, human step)

See **PROGRESS.md → Needs Human Action** for the exact steps.

Short version:
1. Create a Google Cloud project
2. Enable **Google Business Profile API** and **Google Drive API**
3. Create an OAuth 2.0 *Desktop app* credential → download `credentials.json` (do not commit)
4. Request access to the Google Business Profile API (approval may take days)
5. Run the helper script to get your refresh token:
   ```bash
   python scripts/get_refresh_token.py
   ```
6. Copy the printed refresh token into your `.env`

### 3. Fill in config

Edit `config/stores.yaml`:
- Set `location_id` for each store (format: `accounts/{accountId}/locations/{locationId}`)
- Set `drive_folder_id` for each store's photo folder

### 4. Run

```bash
# Dry run (no API writes)
meo-run --dry-run

# Live run
meo-run
```

---

## Project layout

```
config/
  stores.yaml        # per-store location IDs + Drive folder IDs (fill in TODOs)
  content.yaml       # tone, language, banned words, cadence — no code changes needed
src/meo_automation/
  auth.py            # Google OAuth refresh-token flow
  business_profile.py# Google Business Profile API wrapper
  drive.py           # Google Drive image listing/download
  content.py         # AI post + reply generation (LLM abstraction)
  posts.py           # post 最新情報 with photo
  reviews.py         # fetch unreplied reviews, post replies
  main.py            # unattended entrypoint, per-store error isolation
tests/               # mocked unit tests
scripts/
  get_refresh_token.py  # one-time OAuth helper
```

---

## Customizing AI content

All knobs are in `config/content.yaml`:
- `language` — ISO 639-1 code (default `ja`)
- `post_cadence_days` — how often to post per store
- `defaults.tone` — global tone fallback
- `store_overrides.<key>.tone` — per-store tone
- `banned_words` — list of strings the AI must never use
- `post_prompt_template` / `reply_prompt_template` — full prompt templates

To swap the LLM provider: see the `TODO: LLM_PROVIDER` comment in `src/meo_automation/content.py`.

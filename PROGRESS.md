# PROGRESS

## Status: Milestones (a–k) complete + GitHub Actions CI/scheduler + OpenAI provider + location-discovery helper

---

## Completed this run (run 2)

### Test suite — verified green
All 19 unit tests pass (`pytest tests/ -v`).

### Milestone (l) — GitHub Actions CI & scheduled runner

| File | Purpose |
|---|---|
| `.github/workflows/ci.yml` | Run `pytest` on every push / PR to `main` |
| `.github/workflows/daily_run.yml` | Scheduled daily run at 0 UTC (9 AM JST); manual trigger with dry-run/skip flags; uploads `logs/meo.log` as a 30-day artifact |

The daily runner reads credentials from GitHub Actions Secrets — no server or cron required.
**Action needed:** add the four secrets to the repo Settings → Secrets & variables → Actions (see Step 7 below).

### OpenAI provider in content.py
`_call_openai()` is now implemented alongside `_call_anthropic()`.
To switch: set `llm.provider: "openai"` and `llm.model_id: "gpt-4o-mini"` in `config/content.yaml`, then `pip install openai` and export `OPENAI_API_KEY`.
Rate-limit and API errors are caught and re-raised with human-readable messages for both providers.

### Location-discovery helper
`src/meo/tools/discover_locations.py` — run once after GBP API access is granted:

```bash
python -m meo.tools.discover_locations
```

Lists every GBP account and location accessible to the authenticated user and prints ready-to-paste `location_id` values for `config/stores.yaml`.

---

## Previously completed (run 1)

### Milestone (a) — Repo scaffold
- `README.md`, `.gitignore`, `requirements.txt`, `pyproject.toml`
- `config/stores.yaml` — 3 stores with TODO placeholders for location ID + Drive folder ID
- `config/content.yaml` — tone, language=ja, banned words, LLM model, cadence

### Milestones (c–k) — Full source scaffold

| File | Purpose |
|---|---|
| `src/meo/config.py` | YAML config loader |
| `src/meo/auth.py` | Google OAuth2 refresh-token flow; one-time token helper |
| `src/meo/business_profile.py` | GBP REST API: create local posts, list reviews, reply to reviews |
| `src/meo/drive.py` | Drive API v3: list/pick images from store folder |
| `src/meo/content.py` | AI generator: `generate_post()` + `generate_reply()` with Anthropic + OpenAI abstraction |
| `src/meo/posts.py` | 最新情報 post flow per store |
| `src/meo/reviews.py` | Review-fetch-and-reply flow per store |
| `src/meo/main.py` | Unattended entrypoint: all 3 stores, per-store error isolation, dry-run flag |
| `tests/test_config.py` | Config loading tests |
| `tests/test_content.py` | Content generation tests (LLM mocked, both Anthropic + OpenAI branches) |
| `tests/test_posts.py` | Post creation tests (Google mocked) |
| `tests/test_reviews.py` | Review reply tests (Google mocked) |

---

## Needs Human Action

The following steps require the owner to act before the tool can make live API calls.
All code is complete — only configuration and cloud-console steps remain.

---

### Step 1 — Google Cloud project

1. Go to https://console.cloud.google.com/
2. Create a new project (e.g. `meo-automation`).
3. Enable these APIs on the project:
   - **Google My Business API** (Business Profile Performance + Business Information API)
     - Search: "My Business" in API Library
   - **Google Drive API**
     - Search: "Drive API" in API Library

---

### Step 2 — Request Google Business Profile API access

The GBP API is **not publicly available** — you must request access:

1. Fill out the access request form:
   **https://developers.google.com/my-business/content/prereqs**
   (Under "Request access to the API" → click the link to the form)
2. In the form, select your Google Cloud project and describe the use case:
   > "Automated daily 最新情報 posts and review replies for 3 store locations.
   >  Internal tool, not a third-party platform."
3. Approval typically takes 2–7 business days.
4. **Do not proceed to Steps 3–5 until approval is granted.**

---

### Step 3 — OAuth 2.0 Client credentials

1. Google Cloud Console → APIs & Services → Credentials → **Create Credentials** → **OAuth 2.0 Client ID**
2. Application type: **Desktop app** | Name: `meo-automation`
3. Download the client JSON; extract (do NOT commit the file):
   ```
   GOOGLE_CLIENT_ID=<client_id from JSON>
   GOOGLE_CLIENT_SECRET=<client_secret from JSON>
   ```
4. Configure the OAuth consent screen:
   - User type: **Internal** (Google Workspace) or External
   - Scopes to add:
     - `https://www.googleapis.com/auth/business.manage`
     - `https://www.googleapis.com/auth/drive.readonly`

---

### Step 4 — Obtain a refresh token (one-time, on developer machine)

```bash
export GOOGLE_CLIENT_ID=<your_client_id>
export GOOGLE_CLIENT_SECRET=<your_client_secret>
pip install -r requirements.txt
python -m meo.auth
```

Opens a browser for the OAuth consent flow; copy the printed refresh token:
```
GOOGLE_REFRESH_TOKEN=<printed_token>
```

---

### Step 5 — Anthropic API key

1. Sign up / log in at https://console.anthropic.com/
2. Create an API key.
3. Set: `ANTHROPIC_API_KEY=<your_key>`

(Optional — only if switching to OpenAI: `OPENAI_API_KEY=<your_key>`)

---

### Step 6 — Fill in config/stores.yaml (location IDs + Drive folder IDs)

**Find location IDs** — run the discovery helper after API access is granted:

```bash
export GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... GOOGLE_REFRESH_TOKEN=...
python -m meo.tools.discover_locations
```

Copy the printed `location_id` values into `config/stores.yaml`.

**Find Drive folder IDs** — open each photo folder in Google Drive;
copy the ID from the URL: `https://drive.google.com/drive/folders/{FOLDER_ID}`

---

### Step 7 — Add secrets to GitHub (for GitHub Actions scheduler)

In the repo → **Settings → Secrets and variables → Actions**, add:

| Secret name | Value |
|---|---|
| `GOOGLE_CLIENT_ID` | from Step 3 |
| `GOOGLE_CLIENT_SECRET` | from Step 3 |
| `GOOGLE_REFRESH_TOKEN` | from Step 4 |
| `ANTHROPIC_API_KEY` | from Step 5 |

The daily workflow (`.github/workflows/daily_run.yml`) then runs automatically at 9 AM JST.
You can also trigger it manually from the **Actions** tab with a dry-run option.

---

### Step 8 — First dry run (verify everything works)

```bash
python -m meo.main --dry-run
```

Confirm logs show correct store names, generated post text, and selected Drive images.
If everything looks right, run without `--dry-run` (or trigger the GitHub Actions workflow).

---

## Known TODOs in code (non-blocking)

| File | Note |
|---|---|
| `business_profile.py` | GBP requires image upload via media endpoint before attaching; wire up when API access granted and endpoint shape confirmed. Ref: https://developers.google.com/my-business/reference/rest/v4/accounts.locations.media |
| `drive.py` | `download_image()` returns raw bytes; decide hosting strategy (GCS bucket or GBP media endpoint) for non-public Drive files |
| `content.py` | `openai` package is not in requirements.txt; `pip install openai` separately if switching provider |

---

## Next milestone

All code is complete and the test suite is green (19/19).
**The only remaining work is human action** (Steps 1–8 above).

After API access is granted and `config/stores.yaml` is filled in:
1. Run `pytest` to confirm tests still pass.
2. Run `python -m meo.main --dry-run` to verify end-to-end flow.
3. Add GitHub Actions secrets (Step 7) to activate the daily scheduler.
4. Remove `--dry-run` or trigger the workflow without the flag for the first live run.

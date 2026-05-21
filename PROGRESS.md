# PROGRESS

## Status: Milestone (a) + (b) + (c-k scaffold) — COMPLETE

---

## Completed this run

### Milestone (a) — Repo scaffold
- `README.md` — full documentation: layout, env vars, setup, scheduling, security.
- `.gitignore` — blocks all credential files (`*.json`, `.env`, `secrets/`).
- `requirements.txt` + `pyproject.toml` — Python package with `meo-run` entrypoint.
- `config/stores.yaml` — 3 stores (location IDs and Drive folder IDs as TODO placeholders).
- `config/content.yaml` — tone, language=ja, banned words, LLM model, cadence — all configurable.

### Milestone (c) through (k) — Full source scaffold
All modules written and connected end-to-end:

| File | Purpose |
|---|---|
| `src/meo/config.py` | YAML config loader |
| `src/meo/auth.py` | Google OAuth2 refresh-token flow; one-time token helper |
| `src/meo/business_profile.py` | GBP REST API: create local posts, list reviews, reply to reviews |
| `src/meo/drive.py` | Drive API v3: list/pick images from store folder |
| `src/meo/content.py` | AI generator: `generate_post()` + `generate_reply()` with Anthropic abstraction |
| `src/meo/posts.py` | 最新情報 post flow per store |
| `src/meo/reviews.py` | Review-fetch-and-reply flow per store |
| `src/meo/main.py` | Unattended entrypoint: all 3 stores, per-store error isolation, dry-run flag |
| `tests/test_config.py` | Config loading tests |
| `tests/test_content.py` | Content generation tests (LLM mocked) |
| `tests/test_posts.py` | Post creation tests (Google mocked) |
| `tests/test_reviews.py` | Review reply tests (Google mocked) |

---

## Needs Human Action

The following steps require the owner to act before the tool can make live API calls.
Code is complete — only configuration and cloud-console steps remain.

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
4. **Do not proceed to Step 3 until approval is granted.**

---

### Step 3 — OAuth 2.0 Client credentials

1. In Google Cloud Console → APIs & Services → Credentials → **Create Credentials** → **OAuth 2.0 Client ID**
2. Application type: **Desktop app**
3. Name: `meo-automation`
4. Download the client JSON, then **extract** (do NOT commit the file):
   ```
   GOOGLE_CLIENT_ID=<client_id from JSON>
   GOOGLE_CLIENT_SECRET=<client_secret from JSON>
   ```
5. Configure the OAuth consent screen:
   - User type: **Internal** (if using a Google Workspace account) or External
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

This opens a browser for the OAuth consent flow. After approval, the refresh token is printed.
Copy it:
```
GOOGLE_REFRESH_TOKEN=<printed_token>
```

---

### Step 5 — Anthropic API key

1. Sign up / log in at https://console.anthropic.com/
2. Create an API key.
3. Set: `ANTHROPIC_API_KEY=<your_key>`

---

### Step 6 — Fill in config/stores.yaml

For each store, fill in:
- `location_id`: Get it via GBP API after access is approved:
  ```
  GET https://mybusinessbusinessinformation.googleapis.com/v1/accounts/{account_id}/locations
  ```
  The `name` field in each result is the location_id (e.g. `accounts/123456789/locations/987654321`).
- `drive_folder_id`: Open the Google Drive folder in browser; copy the ID from the URL:
  `https://drive.google.com/drive/folders/{FOLDER_ID}`

---

### Step 7 — First dry run (verify everything works)

```bash
python -m meo.main --dry-run
```

Confirm logs show correct store names, generated post text, and selected Drive images.
If everything looks right, run without `--dry-run`.

---

### Step 8 — Set up daily scheduler

**cron** (9 AM JST = 0 UTC):
```cron
0 0 * * * cd /path/to/meo-automation && /path/to/venv/bin/python -m meo.main >> logs/cron.log 2>&1
```

Or use GitHub Actions with repository secrets.

---

## Known TODOs in code (non-blocking)

| File | Line | TODO |
|---|---|---|
| `business_profile.py` | `create_local_post` | GBP requires image upload via media endpoint before attaching; wire up when API access granted and endpoint shape confirmed |
| `drive.py` | `download_image` | Decide hosting strategy for non-public Drive files (GCS or GBP media upload) |
| `content.py` | `_call_llm` | Add OpenAI provider branch if needed |
| `content.py` | `_call_anthropic` | Add graceful handling for `anthropic.APIError` rate limiting |

---

## Next milestone

All code is complete. **The only blocker is human action** (Steps 1–8 above).

After API access is granted and config is filled in, run `pytest` to confirm the test suite passes, then execute a dry run.

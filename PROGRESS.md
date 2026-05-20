# MEO Automation — Progress Log

## Current status: Milestone c complete — starting milestone d next run

---

## Completed milestones

### Milestone a — Repo scaffold (run 1)
- `.gitignore` (secrets, venvs, build artifacts excluded)
- `pyproject.toml` + `requirements.txt` (google-auth stack, anthropic, pyyaml, dotenv)
- `src/meo_automation/__init__.py`
- `tests/__init__.py`
- `README.md` with setup guide and project layout
- `.env.example` documenting all required env vars

### Milestone b — Human action documentation (run 1)
See **Needs Human Action** section below.

### Milestone c — Config files (run 1)
- `config/stores.yaml` — 3 stores with `location_id` and `drive_folder_id` as TODOs
- `config/content.yaml` — language, cadence, tone per store, banned words, prompt templates

---

## Next milestone: d — Google auth module

Implement `src/meo_automation/auth.py`:
- Load credentials from env vars (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`)
- Build a `google.oauth2.credentials.Credentials` object using the refresh-token flow
- Combined scopes: Business Profile + Drive read-only
- Expose `get_credentials() -> google.oauth2.credentials.Credentials`

Then milestone e: Business Profile API client wrapper.

---

## Needs Human Action

These steps require the owner to act before the tool can run against real stores.
Code can be written and tested with mocks in the meantime.

### Step 1 — Create Google Cloud project

1. Go to https://console.cloud.google.com/
2. Click **Select a project → New Project**
3. Name it (e.g. `meo-automation`) and click **Create**

### Step 2 — Enable APIs

In your new project:
1. Go to **APIs & Services → Library**
2. Search for **"Google My Business API"** (also called Business Profile API) → Enable
   - Direct link: https://console.cloud.google.com/apis/library/mybusiness.googleapis.com
3. Search for **"Google Drive API"** → Enable
   - Direct link: https://console.cloud.google.com/apis/library/drive.googleapis.com

### Step 3 — Request Google Business Profile API access

Google Business Profile API requires explicit approval for new projects.

1. Submit the access request form:
   https://developers.google.com/my-business/content/prereqs
   (Click "Request access" and fill out the form)
2. Approval typically takes **3–5 business days**
3. You will receive an email when approved
4. **You can still develop and test with mocks while waiting**

### Step 4 — Create OAuth 2.0 credentials

1. Go to **APIs & Services → Credentials → Create Credentials → OAuth client ID**
2. Application type: **Desktop app**
3. Name it (e.g. `meo-automation-desktop`)
4. Click **Create** → download the JSON file
5. Save it as `credentials.json` in the project root (it is git-ignored)
6. Also set:
   - **APIs & Services → OAuth consent screen**
   - User type: **External**
   - Add scopes:
     - `https://www.googleapis.com/auth/business.manage`
     - `https://www.googleapis.com/auth/drive.readonly`
   - Add your Google account as a **Test user** while in testing mode

### Step 5 — Generate refresh token

Once `credentials.json` exists and API access is approved:

```bash
python scripts/get_refresh_token.py
```

This opens a browser for one-time consent, then prints a refresh token.
Copy it into your `.env` as `GOOGLE_REFRESH_TOKEN`.

### Step 6 — Fill in store IDs in config/stores.yaml

**Location IDs** — for each store:
1. Go to https://business.google.com/
2. Select the location
3. Go to **Settings → Advanced information**
4. The location ID is shown, or derive it from the API after auth is working
   - Format: `accounts/{accountId}/locations/{locationId}`

**Drive folder IDs** — for each store's photo folder:
1. Open the folder in Google Drive
2. The ID is the last segment of the URL:
   `https://drive.google.com/drive/folders/<FOLDER_ID>`

### Step 7 — Get LLM API key

Default LLM is Anthropic Claude.
1. Go to https://console.anthropic.com/
2. Create an API key
3. Set it as `LLM_API_KEY` in your `.env`

---

## Run log

| Run | Date | Milestones completed |
|-----|------|----------------------|
| 1 | 2026-05-20 | a, b, c |

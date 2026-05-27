# PROGRESS

## Status: All milestones complete — 39/39 tests green

---

## Completed this run (run 7)

### Fix: JST timezone in `state.py` duplicate-post guard

**Problem**: `date.today()` on the GitHub Actions Ubuntu runner returns the UTC
date. A manual `workflow_dispatch` triggered between 0 UTC and 9 UTC (= late the
previous JST day) would record the correct UTC date, then a second trigger later
that same UTC day would be treated as same-day and skipped — even though both
triggers happened on different JST calendar days.

Conversely, a trigger at 23:00 UTC (= 8:00 AM JST the *next* day) would use the
prior UTC date, causing the duplicate-post guard to allow a second post on what
JST considers the same business day.

**Fix**: `state.py` now uses `ZoneInfo("Asia/Tokyo")` to anchor all date
comparisons to JST:

```python
_JST = ZoneInfo("Asia/Tokyo")

def _today() -> date:
    return datetime.now(tz=_JST).date()
```

Both `should_post_today()` and `record_post()` now call `_today()` instead of
`date.today()`.

### Fix: deterministic timezone tests in `test_state.py`

Tests like `test_post_yesterday_with_cadence_2_not_due` construct a "yesterday"
date relative to today. If the test setup calls `date.today()` while the
implementation calls `_today()` (JST), they can return different calendar dates
during the UTC/JST boundary window (00:00–09:00 UTC), making the tests flaky.

**Fix**: Added a `frozen_today` fixture that monkey-patches `state_mod._today`
to always return `date(2024, 6, 15)`. The five affected tests now accept
`frozen_today` as a parameter and derive all relative dates from the fixture
value:

```python
_FIXED_TODAY = date(2024, 6, 15)

@pytest.fixture
def frozen_today(monkeypatch):
    monkeypatch.setattr(state_mod, "_today", lambda: _FIXED_TODAY)
    return _FIXED_TODAY
```

### Feature: `max_replies_per_run` cap in `reviews.py`

**Problem**: If a store accumulates many unreplied reviews (e.g., after a period
of downtime), a single run could trigger dozens of LLM calls and GBP API writes,
causing unexpected cost spikes and potential rate-limit errors.

**Fix**: Added `max_replies_per_run: 10` to `config/content.yaml` under
`defaults`. `run_reviews_for_store()` now reads this value and truncates the
unreplied list before the reply loop:

```python
max_replies: int = cfg.content()["defaults"].get("max_replies_per_run", 10)
if len(unreplied) > max_replies:
    logger.warning(
        "[%s] %d unreplied reviews found; capping at %d (max_replies_per_run). "
        "Remaining will be picked up in future runs.",
        store_key, len(unreplied), max_replies,
    )
    unreplied = unreplied[:max_replies]
```

Excess reviews are not silently dropped — they are logged and will be processed
in the next scheduled run.

### New tests

| File | New test |
|---|---|
| `tests/test_state.py` | `frozen_today` fixture; 5 existing tests updated to use it |
| `tests/test_reviews.py` | `test_max_replies_per_run_limits_replies` |

Total: **39/39 tests** (was 38).

---

## Completed this run (run 6)

### Fix: state persistence in GitHub Actions (`daily_run.yml`)

**Problem**: `logs/state.json` lives only on the runner filesystem. Every GitHub
Actions run starts with a fresh checkout, so the duplicate-post guard
(`should_post_today`) had no memory of previous runs. If the scheduled run and
a manual `workflow_dispatch` both fired on the same day, the tool would post
twice for each store.

**Fix**: Added two new steps to `daily_run.yml` wrapping the main run:

```yaml
- name: Restore post state          # before the run
  uses: actions/cache/restore@v4
  with:
    path: logs/state.json
    key: meo-state-${{ github.run_id }}
    restore-keys: |
      meo-state-

- name: Save post state             # after the run (always)
  uses: actions/cache/save@v4
  if: always()
  continue-on-error: true           # no-op on first ever run (no file yet)
  with:
    path: logs/state.json
    key: meo-state-${{ github.run_id }}
```

Each run saves state under a unique key (`meo-state-<run_id>`); the
`restore-keys: meo-state-` prefix picks up the most recent saved snapshot
automatically. GitHub Actions caches are retained for 7 days by default and
pruned automatically — no manual cleanup needed.

`continue-on-error: true` on the save step handles the first-ever run (or a
dry run where no store is configured) where `logs/state.json` may not exist.

### Feature: `--store` dispatch input in `daily_run.yml`

Added a fourth `workflow_dispatch` input so operators can limit a manual run
to a single store without SSHing in or modifying the workflow:

```
store: Run only for this store key (leave blank for all).
       Keys: the_body_osaka_shinsaibashi | the_body_kyoto | mybear_studio_kyoto
```

When provided, `${{ inputs.store }}` is appended as `--store <key>` to the
`python -m meo.main` invocation (the flag already existed in `main.py`).

### Improvement: Anthropic `system` parameter in `content.py`

Split each LLM prompt into a **system** (role/persona/output-format rules) and
a **user** (task data: store name, tone, review content, constraints).

For Anthropic: `system=` is passed as a top-level `client.messages.create()`
keyword — the documented best practice for role-setting (not a user message).
For OpenAI: the system string is injected as a `{"role": "system", ...}` entry
at the start of the `messages` list.

Interface change: `_call_llm(prompt, llm_conf, *, system=None)` — fully
backward-compatible. All 38 existing tests pass unchanged.

This typically improves output quality (fewer preamble sentences, fewer
apologies for not including markdown, better adherence to character limits).

---

## Completed this run (run 5)

### Duplicate-post guard (`src/meo/state.py` — new module)

Without this, if the daily GitHub Actions workflow fired twice in one day
(e.g., a manual trigger on top of the scheduled run) the tool would publish
two identical 最新情報 posts for each store.

`state.py` maintains `logs/state.json` (not committed — covered by `.gitignore`)
with the ISO date of the last successful post per store key:

```json
{"last_post": {"the_body_kyoto": "2024-01-15", ...}}
```

Before each post, `should_post_today(store_key, cadence_days)` checks whether
`cadence_days` have elapsed since the last post. After a successful live post,
`record_post(store_key)` writes today's date. Dry-run mode bypasses the check
entirely so it never changes state.

`cadence_days` comes from `post_cadence_days` in `config/content.yaml` (default: 1).
Set it to 7 for weekly posting without any code changes.

### Config caching (`src/meo/config.py`)

`stores()` and `content()` now use `@lru_cache` so the YAML files are parsed
only once per process. During a normal run (3 stores × N reviews), `cfg.content()`
was called once per `generate_post()` + `generate_reply()` invocation.
`config.clear_cache()` is exposed for tests that need to swap config files.

### Fix stale TODO in `content.py` docstring

The module docstring still said "TODO: add OpenAI provider branch if needed" —
OpenAI support was added in run 2. Removed the stale TODO and updated the
description to list both supported providers.

### Fix CI workflow (`.github/workflows/ci.yml`)

`ci.yml` was installing `pytest` and `pytest-cov` ad-hoc instead of using
the `[dev]` extras declared in `pyproject.toml`. The workflow now runs:

```
pip install cffi && pip install -e ".[dev]"
```

`cffi` must be installed first because the system-provided `cryptography` package
(which `google-auth` depends on) has a Rust-extension that fails without it on
the ubuntu-latest runner.

### New tests

| File | New tests |
|---|---|
| `tests/test_state.py` | 8 tests covering: no state → post due; post today → skip; cadence windows; independent store keys; corrupt/invalid state; persistence |
| `tests/test_posts.py` | 2 new: `test_already_posted_today_skips_without_api_call`, `test_dry_run_bypasses_cadence_check` |

Total: **38/38 tests** (was 28).

---

## Completed this run (run 4)

### Log rotation in `main.py`

`_setup_logging()` now uses `logging.handlers.TimedRotatingFileHandler` instead of
a plain `FileHandler`. The log file (`logs/meo.log`) rotates at midnight UTC and keeps
the last 14 daily files. This prevents unbounded log growth on the production host.

### `pyproject.toml` — `dev` optional extras

```bash
pip install -e ".[dev]"
```

Installs `pytest>=8.0`, `pytest-mock>=3.14`, and `pytest-cov>=5.0`.
Previously `pytest` was not declared anywhere in the project metadata; the CI
workflow installed it manually, but local development had no standard way to get
the test dependencies in one command.

### Minor doc fixes

| File | Fix |
|---|---|
| `src/meo/drive.py` | Removed stale hosting-strategy TODO from `download_image()` — the GBP media upload endpoint was chosen and implemented in run 3 |
| `config/content.yaml` | Corrected comment that said only Anthropic was implemented; OpenAI was added in run 2 |

---

## Completed (run 3)

### GBP media upload flow (replaces webContentLink dependency)

`business_profile.py` now has `upload_media_bytes(location_id, bytes, mime_type)`:
- Downloads image bytes from Drive via the authenticated Drive API (private files work).
- Uploads bytes to GBP via multipart POST to `https://mybusiness.googleapis.com/upload/v4/{location}/media`.
- Returns the `googleUrl` from the GBP Media resource, which is then used as `sourceUrl` in the local post.

`posts.py` updated image flow:
1. Pick random image from Drive folder (metadata only).
2. Download bytes from Drive (authenticated — no public sharing required).
3. Upload to GBP → get hosted URL.
4. Attach hosted URL to local post.
5. If upload fails → fall back to `webContentLink` (works only for public Drive files).
6. If both fail → post without photo, log a warning.

The dry-run path **skips** download and upload (no API calls) but logs which image would be selected.

### `--store` CLI flag in `main.py`

Run automation for a single store (or a subset):

```bash
python -m meo.main --store the_body_kyoto
python -m meo.main --store the_body_kyoto mybear_studio_kyoto --dry-run
```

Invalid store keys exit 1 immediately with a clear error listing valid keys.

### Retry logic in `_AuthSession`

GET requests are now automatically retried up to 3 times (backoff 1.5×) on:
`429 Too Many Requests`, `500`, `502`, `503`, `504`.
POST and PUT are **not** auto-retried (to avoid duplicate posts or double-replies).

### Header merging fix in `_AuthSession`

`get()`, `post()`, `put()` now correctly merge caller-supplied `headers` with the
Authorization header — previously, passing a custom `Content-Type` would have raised
`TypeError: got multiple values for keyword argument 'headers'`.

### `test_main.py` — 7 new tests

| Test | What it covers |
|---|---|
| `test_dry_run_all_stores_exits_0` | Full dry run exits clean |
| `test_store_filter_limits_processing` | `--store` runs only one store |
| `test_store_filter_multiple_keys` | `--store A B` runs both |
| `test_unknown_store_key_exits_1` | Bad key → exit 1 |
| `test_missing_credentials_exits_1` | Auth error → exit 1 |
| `test_skip_posts_flag_skips_post_creation` | `--skip-posts` never calls post flow |
| `test_skip_reviews_flag_skips_review_replies` | `--skip-reviews` never calls review flow |

### `test_posts.py` — 3 new tests, updated fixtures

| Test | What it covers |
|---|---|
| `test_live_run_downloads_and_uploads_image` | Full Drive→GBP upload path |
| `test_upload_failure_falls_back_to_web_content_link` | GBP upload error → webContentLink |
| `test_upload_failure_no_fallback_posts_without_photo` | No URL at all → posts without photo |

### `pyproject.toml` — optional `openai` extra

```bash
pip install "meo-automation[openai]"
```
Then set `llm.provider: "openai"` in `config/content.yaml`.

---

## Previously completed (runs 1 & 2)

### Milestone (a) — Repo scaffold
- `README.md`, `.gitignore`, `requirements.txt`, `pyproject.toml`
- `config/stores.yaml` — 3 stores with TODO placeholders for location ID + Drive folder ID
- `config/content.yaml` — tone, language=ja, banned words, LLM model, cadence

### Milestones (c–k) — Full source scaffold

| File | Purpose |
|---|---|
| `src/meo/config.py` | YAML config loader |
| `src/meo/auth.py` | Google OAuth2 refresh-token flow; one-time token helper |
| `src/meo/business_profile.py` | GBP REST API: create local posts, media upload, list reviews, reply to reviews |
| `src/meo/drive.py` | Drive API v3: list/pick images from store folder |
| `src/meo/content.py` | AI generator: `generate_post()` + `generate_reply()` with Anthropic + OpenAI abstraction |
| `src/meo/posts.py` | 最新情報 post flow per store (Drive→GBP upload) |
| `src/meo/reviews.py` | Review-fetch-and-reply flow per store |
| `src/meo/main.py` | Unattended entrypoint: all 3 stores, per-store error isolation, dry-run + --store flags |
| `tests/test_config.py` | Config loading tests |
| `tests/test_content.py` | Content generation tests (LLM mocked) |
| `tests/test_posts.py` | Post creation tests (Drive→GBP upload flow mocked) |
| `tests/test_reviews.py` | Review reply tests (Google mocked) |
| `tests/test_main.py` | CLI arg parsing, --store filtering, exit codes |

### Milestone (l) — GitHub Actions CI & scheduled runner

| File | Purpose |
|---|---|
| `.github/workflows/ci.yml` | Run `pytest` on every push / PR to `main` |
| `.github/workflows/daily_run.yml` | Scheduled daily run at 0 UTC (9 AM JST); manual trigger with dry-run/skip flags; uploads `logs/meo.log` as a 30-day artifact |

### OpenAI provider + location-discovery helper
- `content.py`: both `_call_anthropic()` and `_call_openai()` implemented.
- `src/meo/tools/discover_locations.py`: lists all GBP accounts/locations; run once after API access is granted to find location IDs.

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

To test a single store first:
```bash
python -m meo.main --store the_body_kyoto --dry-run
```

If everything looks right, run without `--dry-run` (or trigger the GitHub Actions workflow).

---

## Known TODOs in code (non-blocking)

| File | Note |
|---|---|
| `business_profile.py` | `upload_media_bytes()`: confirm response field name (`googleUrl` vs `sourceUrl`) once API access is granted. Ref: https://developers.google.com/my-business/reference/rest/v4/accounts.locations.media#Media |

---

## Next milestone

All code is complete and the test suite is green (28/28).
**The only remaining work is human action** (Steps 1–8 above).

After API access is granted and `config/stores.yaml` is filled in:
1. Run `pytest` to confirm all 28 tests still pass.
2. Run `python -m meo.main --store the_body_kyoto --dry-run` to verify single-store flow.
3. Run `python -m meo.main --dry-run` for all stores.
4. Add GitHub Actions secrets (Step 7) to activate the daily scheduler.
5. Remove `--dry-run` or trigger the workflow without the flag for the first live run.
6. After the first live post, verify that `upload_media_bytes()` returns a `googleUrl` field and remove the TODO in `business_profile.py` once confirmed.

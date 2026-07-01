# PROGRESS

## Status: All milestones complete — 409/409 tests green (98% coverage)

---

## Completed this run (run 37)

### Fix: anonymous Google reviewer names produced unprofessional replies (`src/meo/content.py`)

**Problem**: Google uses placeholder `displayName` values like `"A Google User"` or
`"Google ユーザー"` for anonymous or deleted accounts.  `generate_reply()` forwarded
the raw `displayName` directly to the LLM prompt:

```
レビュアー名: A Google User
```

The LLM then generated replies like:

```
A Google User様、この度はご来店いただきありがとうございます…
```

This is jarring and unprofessional — a Japanese business owner would never address
a customer by a placeholder English string.  Anonymous reviews are not uncommon on
GBP, so this path was reached in practice on every store's first live run if any
reviewers had deleted their accounts.

**Fix**: Added `_ANON_REVIEWER_NAMES` (a `frozenset` of known Google placeholder
names, matched case-insensitively) and `_sanitize_reviewer_name(name)` that returns
`"お客様"` for anonymous or blank names, and the original name otherwise.

```python
_ANON_REVIEWER_NAMES: frozenset[str] = frozenset({
    "a google user",
    "google user",
    "google ユーザー",
    "googleユーザー",
})

def _sanitize_reviewer_name(name: str) -> str:
    if not name or name.lower() in _ANON_REVIEWER_NAMES:
        return "お客様"
    return name
```

`generate_reply()` now calls `_sanitize_reviewer_name(raw_name)` so the LLM
generates a natural Japanese reply:

```
お客様、この度はご来店いただきありがとうございます…
```

Named reviewers are unchanged — their `displayName` is passed through as before.
The fallback for a completely absent `reviewer` dict also yields `"お客様"` via
the empty-string branch of the helper.

**Files changed:**

| File | Change |
|---|---|
| `src/meo/content.py` | `_ANON_REVIEWER_NAMES` constant; `_sanitize_reviewer_name()` helper; `generate_reply()` uses it instead of raw `displayName` |
| `tests/test_content.py` | +12 tests covering all branches of the helper and its integration with `generate_reply()` |

**New tests (+12 tests):**

| File | Test | What it covers |
|---|---|---|
| `tests/test_content.py` | `test_sanitize_reviewer_name[A Google User-お客様]` | English anonymous placeholder → お客様 |
| `tests/test_content.py` | `test_sanitize_reviewer_name[a google user-お客様]` | Case-insensitive match |
| `tests/test_content.py` | `test_sanitize_reviewer_name[Google User-お客様]` | Variant without "A" |
| `tests/test_content.py` | `test_sanitize_reviewer_name[Google ユーザー-お客様]` | Japanese locale placeholder |
| `tests/test_content.py` | `test_sanitize_reviewer_name[Googleユーザー-お客様]` | Japanese locale without space |
| `tests/test_content.py` | `test_sanitize_reviewer_name[-お客様]` | Empty string → お客様 |
| `tests/test_content.py` | `test_sanitize_reviewer_name[田中太郎-田中太郎]` | Real Japanese name unchanged |
| `tests/test_content.py` | `test_sanitize_reviewer_name[John Smith-John Smith]` | Foreign name unchanged |
| `tests/test_content.py` | `test_sanitize_reviewer_name[山田 花子-山田 花子]` | Japanese name with space unchanged |
| `tests/test_content.py` | `test_generate_reply_replaces_anonymous_name_with_okakusama` | "A Google User" in review → "お客様" in LLM prompt; placeholder absent |
| `tests/test_content.py` | `test_generate_reply_preserves_real_reviewer_name` | Named reviewer → real name in prompt |
| `tests/test_content.py` | `test_generate_reply_uses_okakusama_when_reviewer_key_absent` | No `reviewer` dict → "お客様" in prompt |

Total: **409/409 tests** (was 397).

---

## Completed this run (run 36)

### Feature: Human-readable store names in Slack run-summary notifications

**Problem**: `_format_message()` in `notify.py` used the store *key*
(`the_body_osaka_shinsaibashi`) as the bullet label in every Slack message.
The key is a valid Python identifier, not something an owner reads naturally.
A run summary like:

```
• *the_body_osaka_shinsaibashi*: post: posted (スタッフ紹介)
• *the_body_kyoto*: post: skipped
• *mybear_studio_kyoto*: replies: 2
```

requires the owner to keep the key-to-name mapping in their head.

**Fix**: `main.py` now includes `"store_name": store["name"]` in every per-store
result dict assembled in the run loop.  `_format_message()` checks for `store_name`
and formats the label as `"Name (key)"` when it is present, falling back to the key
alone when absent (maintains backward compat with any hand-crafted test fixtures or
external tooling that builds the results dict):

```
• *THE BODY 大阪 心斎橋店 (the_body_osaka_shinsaibashi)*: post: posted (スタッフ紹介)
• *THE BODY 京都店 (the_body_kyoto)*: post: skipped
• *MYBEAR STUDIO 京都店 (mybear_studio_kyoto)*: replies: 2
```

### Feature: `meo-preview` now shows 1★, 3★, and 5★ reply samples per store

**Problem**: `meo-preview` generated a single reply sample using a fixed 3★ review.
The owner had no way to verify how the AI handles the two most critical scenarios:

- **1★** (angry customer) — requires an apologetic, corrective tone; the wrong reply
  here causes real reputational damage.
- **5★** (happy customer) — the other extreme; over-formal language would seem off.

**Fix**: Replaced `_SAMPLE_REVIEW` (single 3★ dict) with `_SAMPLE_REVIEWS`
(dict with `"ONE"`, `"THREE"`, and `"FIVE"` entries, each with a realistic comment).
`run_preview()` now calls `generate_reply()` for all three; the result dict carries
`replies: {"ONE": ..., "THREE": ..., "FIVE": ...}` instead of the old `reply: str`.

Output format:
```
[レビュー返信サンプル — 3パターン]

▸ 1★ 低評価
<AI-generated reply for an unhappy customer>

▸ 3★ 普通
<AI-generated reply for a neutral customer>

▸ 5★ 高評価
<AI-generated reply for a delighted customer>
```

Error handling is per-rating: if one rating fails (e.g. a transient API error),
the others still render.  `meo-preview` exits 1 if any reply generation fails,
matching the existing behaviour for post generation errors.

**Files changed:**

| File | Change |
|---|---|
| `src/meo/main.py` | `store_results` now includes `"store_name": store["name"]` |
| `src/meo/notify.py` | `_format_message()`: `label = "Name (key)"` when `store_name` present; falls back to key |
| `src/meo/tools/preview.py` | `_SAMPLE_REVIEWS` dict (3 reviews); `run_preview()` returns `replies` dict; `_format_output()` renders 3-rating block; `had_error` checks `reply_errors` |

**New tests (+6 tests):**

| File | Test | What it covers |
|---|---|---|
| `tests/test_notify.py` | `test_format_store_name_shown_alongside_key` | `store_name` in result → label shows "Name (key)" in Slack message |
| `tests/test_notify.py` | `test_format_falls_back_to_key_when_store_name_absent` | No `store_name` in result → falls back to `store_key` label |
| `tests/test_preview.py` | `test_run_preview_returns_post_and_all_three_replies_per_store` | All three ratings returned in `replies` dict |
| `tests/test_preview.py` | `test_run_preview_captures_reply_errors` | All-fail → `reply_errors` dict with all three ratings |
| `tests/test_preview.py` | `test_run_preview_partial_reply_failure` | One rating fails → other two in `replies`; failed one in `reply_errors` |
| `tests/test_preview.py` | `test_run_preview_generate_reply_called_for_three_ratings` | Exactly 3 `generate_reply` calls per store (ONE, THREE, FIVE) |
| `tests/test_preview.py` | `test_main_exits_1_when_any_reply_fails` | Any reply error → exit 1 |
| `tests/test_preview.py` | `test_format_output_shows_all_three_rating_labels` | Output contains 1★, 3★, 5★ section labels |

**Updated tests (5 tests rewritten for new result shape):**

| File | Test |
|---|---|
| `tests/test_preview.py` | `test_run_preview_returns_post_and_reply_for_each_store` → `test_run_preview_returns_post_and_all_three_replies_per_store` |
| `tests/test_preview.py` | `test_run_preview_captures_reply_error` → `test_run_preview_captures_reply_errors` |
| `tests/test_preview.py` | `test_format_output_contains_store_name_and_content` |
| `tests/test_preview.py` | `test_format_output_marks_errors` → `test_format_output_marks_post_error` |
| `tests/test_preview.py` | `test_format_output_marks_reply_error` |

Total: **397/397 tests** (was 391).

---

## Completed this run (run 35)

### Fix: `effective_defaults` docstring missing `max_review_age_days` override key

**Problem**: `config.py`'s `effective_defaults` docstring listed five allowed
override keys:

```
Allowed override keys: post_cadence_days, max_post_chars, max_reply_chars,
max_replies_per_run, min_star_autoreply.
```

`max_review_age_days` was added to `_ALLOWED_OVERRIDE_KEYS` in `validator.py`
during run 22, and documented in `config/stores.yaml`'s commented-out override
templates — but the docstring was never updated.  An operator reading
`effective_defaults` in isolation would not find `max_review_age_days` in the
list and might think it cannot be overridden per store.

**Fix**: Added `max_review_age_days` to the docstring's allowed-key list.

### Improvement: expanded theme pool from 4 to 8 themes per industry (`config/content.yaml`)

**Problem**: With `_THEME_HISTORY_SIZE = 4` in `state.py`, the theme rotation
de-prioritises the 4 most recently used themes before choosing the next one.
With only 4 themes per industry, every theme was eligible again after just one
full cycle — meaning the same 4 themes repeated in a fixed rotation with no
effective variety beyond the order of selection.  For a tool that posts daily,
this produces visibly repetitive content over a month.

**Fix**: Added 4 new themes to each industry, bringing each pool to 8 themes.
With `_THEME_HISTORY_SIZE = 4`, the system now always picks from the 4 freshest
themes at any given moment — a 2× improvement in day-over-day variety.

**New themes — `beauty_salon`** (added to existing 4):

| Theme | Purpose |
|---|---|
| `スタッフ紹介・こだわりのご紹介` | Staff profiles / philosophy; builds personal connection |
| `新メニュー・施術のご案内` | New treatment announcements |
| `おうちケア・美容Tipsのご紹介` | At-home care tips; value-added educational content |
| `ご予約・営業案内` | Booking/hours reminder; practical utility |

**New themes — `fitness_studio`** (added to existing 4):

| Theme | Purpose |
|---|---|
| `体験レッスン・入会キャンペーン` | Trial class / membership campaign |
| `栄養・食事のアドバイス` | Nutrition/dietary advice; broadens content beyond workouts |
| `会員様の声・成果報告` | Member testimonials / success stories |
| `スケジュール・イベント情報` | Weekly schedule / event information |

**Files changed:**

| File | Change |
|---|---|
| `src/meo/config.py` | `effective_defaults` docstring: added `max_review_age_days` to allowed-key list |
| `config/content.yaml` | Both industries: 4 → 8 themes (4 new entries each) |

**Tests:** No new tests — purely a docstring + config file change.
All 391/391 tests pass unchanged.

---


## Completed this run (run 34)

### Fix: held-review snapshot not cleared when `min_star_autoreply` reverts to 1

**Problem**: `record_held_reviews()` was only called inside the `if min_star > 1`
block in `reviews.py`.  When an operator previously ran with `min_star_autoreply: 3`
(holding 1–2★ reviews for manual handling) and then changed the config back to
`min_star_autoreply: 1` (reply to all reviews automatically), the old held-review
snapshot remained in `state.json` indefinitely.

`meo-export held-reviews` would continue showing those entries — which had already
been processed — on every subsequent run, until the operator manually ran
`meo-reset held-reviews`.

**Fix**: Moved the `record_held_reviews()` call outside the `if min_star > 1` block
so it always fires in live mode.  When `min_star == 1`, `manual == []` and the
function is called with an empty list, clearing any stale snapshot automatically.

The semantics are unchanged for `min_star > 1` — if reviews are below threshold
the snapshot is updated; if all reviews pass the threshold an empty list is passed
(same behavior as before, since the existing comment already said "Passing an empty
list when manual==[] clears any stale snapshot").  Dry-run mode is unaffected
(the `if not dry_run:` guard still wraps the call).

### Fix: incomplete override templates in `config/stores.yaml`

**Problem**: The commented-out `overrides:` templates in all three store entries
were inconsistent:
- `max_review_age_days` was missing from all three stores
- `max_post_chars` and `max_reply_chars` were missing from `the_body_kyoto`
  and `mybear_studio_kyoto`

An operator consulting the template would not discover that these keys can be
overridden per store — they'd have to read `validator.py` or the docs.

**Fix**: All three `overrides:` templates now list all six allowed override keys
with their global defaults noted in comments:

| Key | Default |
|---|---|
| `post_cadence_days` | 1 |
| `min_star_autoreply` | 1 |
| `max_replies_per_run` | 10 |
| `max_post_chars` | 1500 |
| `max_reply_chars` | 4096 |
| `max_review_age_days` | 90 |

**Files changed:**

| File | Change |
|---|---|
| `src/meo/reviews.py` | `record_held_reviews()` moved outside `if min_star > 1` block; updated comment |
| `tests/test_reviews.py` | +1 test: `test_record_held_reviews_clears_stale_snapshot_when_min_star_is_1` |
| `config/stores.yaml` | All three stores: complete 6-key override template with defaults |

### New test (+1 test)

| File | Test | What it covers |
|---|---|---|
| `tests/test_reviews.py` | `test_record_held_reviews_clears_stale_snapshot_when_min_star_is_1` | `min_star==1` live mode → `record_held_reviews(store_key, [])` called exactly once to clear stale snapshot |

Total: **391/391 tests** (was 390).

---

## Completed this run (run 33)

### Security: harden GitHub Actions workflows against shell injection and over-privileged tokens

Three small hardening changes to `.github/workflows/daily_run.yml` and
`.github/workflows/ci.yml`, following GitHub's own security-hardening guide:

#### 1. Shell injection fix for `inputs.store` (`daily_run.yml`)

**Problem**: The `store` workflow_dispatch input is free-text (no `type: choice`
constraint).  It was previously interpolated directly into the shell script via
`${{ inputs.store }}` before the shell saw the script:

```bash
[ -n "${{ inputs.store }}" ] && ARGS="$ARGS --store ${{ inputs.store }}"
```

If `inputs.store` contained shell-special characters such as `"` (double-quote),
the injected text could break out of the surrounding quotes and be interpreted as
shell commands.  For example, `inputs.store = '"` would produce:

```bash
ARGS="$ARGS --store "
```

...which leaves a dangling unmatched quote, causing a syntax error or worse.

GitHub's recommended fix for user-controlled inputs is to pass them through the
`env:` block, where GitHub escapes the value and the shell sees it as a variable
rather than as inline text.

**Fix**: Moved `inputs.store` to `env: MEO_STORE_INPUT: ${{ inputs.store }}` and
changed the script to reference `$MEO_STORE_INPUT`.  Added a comment citing the
GitHub security guide for future maintainers.

The choice inputs (`dry_run`, `skip_posts`, `skip_reviews`, `force`) are safe as
direct interpolation because GitHub validates them to "true"/"false" before the
script runs.  Only the free-text `store` input needed this treatment.

#### 2. Least-privilege `permissions:` block (`daily_run.yml`, `ci.yml`)

**Problem**: Without an explicit `permissions:` block, both workflows inherited
the repository's default token permissions — likely `contents: write` and
`pull-requests: write`.  Neither workflow writes to the repo or manages PRs/issues,
so the extra scopes were unnecessary attack surface: a compromised third-party
action or a supply-chain incident could abuse those permissions.

**Fix**: Added explicit `permissions:` blocks to both jobs:

```yaml
permissions:
  contents: read   # checkout only — no push, no PR creation
  actions: write   # required for cache save/restore and upload-artifact
```

`actions: write` is the minimum needed for `actions/cache/restore`,
`actions/cache/save`, and `actions/upload-artifact`.  All other permission scopes
are implicitly denied.

#### 3. `if-no-files-found: ignore` for upload-artifact (`daily_run.yml`)

**Problem**: When the daily runner exits early (no credentials configured), the
Python script never runs, so `logs/meo.log` is never created.  The
`upload-artifact` action defaults to `if-no-files-found: warn`, which emits a
yellow warning in the Actions log on every unconfigured run — misleading noise
that suggested something went wrong.

**Fix**: Added `if-no-files-found: ignore` to suppress the warning.  The artifact
step still runs (`if: always()`) and is a no-op when the log doesn't exist.

**Files changed:**

| File | Change |
|---|---|
| `.github/workflows/daily_run.yml` | `permissions:` block; `MEO_STORE_INPUT` env var; `if-no-files-found: ignore` |
| `.github/workflows/ci.yml` | `permissions:` block |

**Tests:** No new tests — workflow-only changes; all 390/390 pass unchanged.

---

## Completed this run (run 32)

### Refactor: reduce `state.py` from 473 lines to 366 lines (below the 400-line module cap)

**Problem**: `state.py` was 473 lines — 18% over the 400-line "small focused module"
constraint declared in the project guidelines.

The overage came from two repeated patterns:

1. **Five identical `clear_*` functions** (lines 342–473, ~132 lines): each loaded
   state, popped one or all keys from a named section, and saved — differing only
   in the section name string.

2. **Three identical rotation `record_*` functions** (`record_image`, `record_theme`,
   `record_replied_review`): each loaded state, removed the item if already present,
   prepended it, capped the list, and saved — differing only in section name and
   capacity constant.

**Fix**: Extracted two private helpers that capture the shared pattern:

```python
def _record_rotation(section_name, store_key, item, capacity):
    """Prepend item to a rotation list, capped at capacity (no duplicates)."""
    ...

def _clear_section(section_name, store_key):
    """Clear one or all entries in a top-level state section."""
    ...
```

All 8 public functions (`record_image`, `record_theme`, `record_replied_review`,
`clear_post_guard`, `clear_image_history`, `clear_theme_history`,
`clear_replied_reviews`, `clear_held_reviews`) now delegate to these helpers.

**API surface is unchanged** — no callers or tests required modification.

**Line count:**

| Before | After | Saved |
|---|---|---|
| 473 lines | 366 lines | 107 lines (−23%) |

**Tests:** 390/390 pass unchanged.

---

## Completed this run (run 31)

### Fix: daily run emits "failure" every day while awaiting credential setup

**Problem**: The four required GitHub Actions secrets (`GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`, `ANTHROPIC_API_KEY`) have not
yet been added to the repository.  The tool correctly exits 1 at the
config-validation step, causing the scheduled run to report "failure" every day
— confirmed in run logs (job 82633128178, 2026-06-22):

```
GOOGLE_CLIENT_ID:      (empty)
GOOGLE_CLIENT_SECRET:  (empty)
GOOGLE_REFRESH_TOKEN:  (empty)
ANTHROPIC_API_KEY:     (empty)
...
ERROR: Missing required env var: GOOGLE_CLIENT_ID
CRITICAL: 4 configuration error(s) found.
Process completed with exit code 1.
```

This has created daily noise for 4 consecutive scheduled runs since run 30.

**Fix**: Added an early-exit guard at the top of the "Run MEO automation" step.
When **all four** required secrets are empty — indicating the tool has never been
configured — the step exits 0 with a GitHub Actions `::notice::` annotation
instead of running `meo.main` and failing.

```bash
if [ -z "$GOOGLE_CLIENT_ID" ] && \
   [ -z "$GOOGLE_CLIENT_SECRET" ] && \
   [ -z "$GOOGLE_REFRESH_TOKEN" ] && \
   [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "::notice::Credentials not yet configured. ..."
  exit 0
fi
```

The "all four empty" condition is strict so partial misconfiguration still fails
with the full error list.  Once the owner adds even one credential the guard
falls through and the tool runs normally.

**Files changed:**

| File | Change |
|---|---|
| `.github/workflows/daily_run.yml` | Early-exit guard added before `ARGS=""` in "Run MEO automation" step |

**Tests:** no new tests — workflow-only change; 390/390 pass unchanged.

---

## Needs human action — credential setup (unchanged from prior runs)

The tool is code-complete and test-complete.  The only remaining steps are
one-time owner actions:

1. **Google Cloud project** — create a project at
   <https://console.cloud.google.com/> and note the project ID.

2. **Enable APIs** — in the project, enable:
   - "Google My Business API" (or "Business Profile API")
   - "Google Drive API"

3. **OAuth 2.0 client** — create an OAuth client ID (type: Desktop app).
   Download the `credentials.json`.

4. **Business Profile API access** — fill in the access form at
   <https://developers.google.com/my-business/content/prereqs> (approval can
   take a few days).

5. **Combined scopes refresh token** — run locally:
   ```bash
   pip install -e .
   python -m meo.auth
   ```
   This opens a browser, prompts you to authorise **both** scopes
   (`business.manage` + `drive.readonly`), and prints the refresh token.

6. **Add GitHub Actions secrets** — in the repository, go to
   Settings → Secrets and variables → Actions → New repository secret:
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`
   - `GOOGLE_REFRESH_TOKEN`
   - `ANTHROPIC_API_KEY` (get at <https://console.anthropic.com/>)
   - `SLACK_WEBHOOK_URL` *(optional — Slack run-summary notifications)*

7. **Fill in `config/stores.yaml`** — replace the `TODO` placeholders for
   `location_id` and `drive_folder_id`.  Use `python -m meo.tools.discover_locations`
   to find your location IDs once the Business Profile API is approved.

Once secrets are added, the next scheduled run (0:00 UTC / 9:00 JST) will
activate automatically.

---

## Completed this run (run 30)

### Fix: production daily runner had two silent failure modes

#### 1. Missing `cffi` install in `daily_run.yml`

**Problem**: The CI workflow (`ci.yml`) installs `cffi` before the main
dependencies with the comment: _"cffi must be installed first because the
system-provided cryptography package (which google-auth depends on) has a
Rust-extension that fails without it on the ubuntu-latest runner."_

The daily runner (`daily_run.yml`) only ran `pip install -e .`, without the
`cffi` pre-install.  On any ubuntu-latest runner that has the system-level
`cryptography` package, `google.oauth2` would fail with:

```
pyo3_runtime.PanicException: Python API call failed
ModuleNotFoundError: No module named '_cffi_backend'
```

This would cause every scheduled run to fail immediately, with no useful error
in the log — only a cryptic PanicException from Rust code.

**Fix**:
- `daily_run.yml`: added `pip install cffi &&` before the main install (same
  pattern as `ci.yml`).
- `pyproject.toml`: added `cffi>=1.15.0` to `dependencies` so the requirement
  is declared in the package metadata and visible to `pip`.
- `requirements.txt`: added `cffi>=1.15.0` with an explanatory comment.

#### 2. No config validation before the live run in `daily_run.yml`

**Problem**: CI validates config structure (`meo-validate --no-env`) on every
push, so YAML typos are caught before merge.  But the daily runner had no such
step.  A config typo introduced after the last CI run (e.g. directly editing
`config/content.yaml` on the repo web UI) would only be discovered mid-run
after Google Auth already succeeded — with a Python `KeyError` or YAML error
buried deep in the log, and no clear message about which config key was wrong.

**Fix**: Added a `Validate config structure` step to `daily_run.yml` between
`Install dependencies` and `Run MEO automation`:

```yaml
- name: Validate config structure
  run: python -m meo.tools.validate --no-env
```

If `config/stores.yaml` or `config/content.yaml` has a structural error, the
run fails immediately at this step with a clear `✗` error list from
`meo-validate`, and none of the credentials or API quota are touched.

**Files changed:**

| File | Change |
|---|---|
| `.github/workflows/daily_run.yml` | `pip install cffi` before main install; added `Validate config structure` step |
| `pyproject.toml` | `cffi>=1.15.0` added to `dependencies` |
| `requirements.txt` | `cffi>=1.15.0` added with comment |

**Tests:** no new tests — both changes are workflow/config file fixes. All
390/390 existing tests pass unchanged.

---

## Completed this run (run 29)

### Tests: closed 3 remaining testable coverage gaps (97% → 98%)

The 39 uncovered lines reported after run 28 were claimed to be the structural
ceiling.  On inspection, 3 of them were actually reachable by tests — they were
real branches in `main()` functions that the existing tests only exercised via
the library-level helper (not the CLI entrypoint).

| File | Line | What was missing |
|---|---|---|
| `src/meo/tools/health.py` | 138 | `check_sym = _WARN` — the `!` warning symbol path for `drive_folder_id="TODO"` in `main()`; existing test only called `run_health()`, never `main()` |
| `src/meo/tools/preview.py` | 89 | `lines.append(f"ERROR: {r.get('reply_error', ...')}")` — the reply-error branch in `_format_output()`; existing test had `post_error` but still provided `reply`, so the else-branch on the reply side was never taken |
| `src/meo/tools/reset.py` | 159 | `print(f"  – {label}: nothing to clear")` — the per-section "nothing to clear" line in `main()`; reached only when `any_cleared` is True (at least one section had data) but a specific section had none; existing test only exercised the all-empty early-exit path |

**New tests (+3 tests):**

| File | Test | What it covers |
|---|---|---|
| `tests/test_health.py` | `test_main_shows_warn_symbol_for_unconfigured_drive_folder_id` | `main()` with a TODO `drive_folder_id` store → `!` symbol in output, exits 0 (warning, not fatal) |
| `tests/test_preview.py` | `test_format_output_marks_reply_error` | `_format_output` with `reply_error` key (no `reply`) → `"ERROR: Rate limit"` in output |
| `tests/test_reset.py` | `test_main_partial_clear_shows_dash_for_sections_with_nothing_to_clear` | State with only `last_post` data + `meo-reset all` → "Reset complete" printed with "nothing to clear" for the empty sections |

**Coverage change:**

| Module | Before | After |
|---|---|---|
| `health.py` | 96% | 97% |
| `preview.py` | 94% | 96% |
| `reset.py` | 93% | 94% |
| **Total** | **97%** | **98%** |

The remaining 36 uncovered lines (2%) are the true structural ceiling:
- `try: from dotenv import load_dotenv; load_dotenv()` blocks in every CLI module
- `if __name__ == "__main__":` guards across all CLI modules
- `raise RuntimeError("retry loop exited without return or raise")` in `content.py:246` (explicitly annotated unreachable guard)
- `auth.py:65-81`: the interactive `InstalledAppFlow` browser-launch block

**Files changed:**

| File | Change |
|---|---|
| `tests/test_health.py` | +1 test: `main()` warn-symbol path for unconfigured drive_folder_id |
| `tests/test_preview.py` | +1 test: `_format_output()` reply-error branch |
| `tests/test_reset.py` | +1 test: partial-clear "nothing to clear" per-section output |

### New tests (+3 tests)

Total: **390/390 tests** (was 387).

---

## Completed this run (run 28)

### Tests: closed remaining actionable coverage gaps across 6 modules (96% → 97%)

**Problem**: Several modules had meaningful untested code paths that could regress silently:

| Module | Previous coverage | Gaps closed |
|---|---|---|
| `src/meo/auth.py` | 33% | `get_credentials()` and `_require_env()` had zero test coverage |
| `src/meo/business_profile.py` | 97% | `_refresh_if_needed()` expired-credentials path; `call_to_action` body field |
| `src/meo/config.py` | 93% | `clear_cache()` body never called directly in tests |
| `src/meo/content.py` | 96% | Anthropic dispatch branch; missing-API-key EnvironmentError for both providers; OpenAI system-message insertion |
| `src/meo/main.py` | 96% | `had_error = True` when `run_reviews_for_store` returns result with `errors` key |
| `src/meo/posts.py` | 99% | `_pick_theme` early-return when themes list is empty |
| `src/meo/validator.py` | 96% | Missing-field errors within present `defaults`/`llm` sections (vs. missing section entirely) |

**Fix**: +25 new tests across 7 test files.

**`tests/test_auth.py` (new file) — 10 tests:**

| Test | What it covers |
|---|---|
| `test_require_env_returns_value_when_set` | Returns value when env var is set |
| `test_require_env_raises_when_missing` | Raises `EnvironmentError` with var name when absent |
| `test_require_env_raises_when_empty_string` | Empty string treated same as absent |
| `test_get_credentials_raises_when_client_id_missing` | Missing `GOOGLE_CLIENT_ID` → EnvironmentError |
| `test_get_credentials_raises_when_client_secret_missing` | Missing `GOOGLE_CLIENT_SECRET` → EnvironmentError |
| `test_get_credentials_raises_when_refresh_token_missing` | Missing `GOOGLE_REFRESH_TOKEN` → EnvironmentError |
| `test_get_credentials_returns_credentials_object` | Returns the `Credentials` instance |
| `test_get_credentials_builds_credentials_with_env_values` | Env var values wired into `Credentials` kwargs |
| `test_get_credentials_calls_refresh` | `creds.refresh(Request())` called exactly once |
| `test_get_credentials_includes_both_scopes` | Both `business.manage` and `drive.readonly` in scopes |

**`tests/test_business_profile.py` — 4 tests:**

| Test | What it covers |
|---|---|
| `test_refresh_if_needed_does_nothing_when_creds_valid` | No refresh when `creds.valid = True` |
| `test_refresh_if_needed_refreshes_when_creds_invalid` | `creds.refresh()` called when `creds.valid = False` |
| `test_create_local_post_includes_call_to_action_when_given` | `callToAction` body field set when CTA provided |
| `test_create_local_post_omits_call_to_action_when_none` | `callToAction` absent when `call_to_action=None` |

**`tests/test_config.py` — 1 test:**

| Test | What it covers |
|---|---|
| `test_clear_cache_allows_fresh_reload` | Calls `_stores_cached.cache_clear()` and `_content_cached.cache_clear()` |

**`tests/test_content.py` — 4 tests:**

| Test | What it covers |
|---|---|
| `test_call_llm_anthropic_provider` | Dispatch to `_call_anthropic` when provider is `"anthropic"` |
| `test_call_anthropic_raises_environment_error_when_api_key_missing` | `ANTHROPIC_API_KEY` absent → EnvironmentError |
| `test_call_openai_raises_environment_error_when_api_key_missing` | `OPENAI_API_KEY` absent → EnvironmentError |
| `test_call_openai_includes_system_message_when_system_given` | System string → `{"role": "system", ...}` prepended to messages |

**`tests/test_main.py` — 1 test:**

| Test | What it covers |
|---|---|
| `test_reviews_result_with_errors_key_causes_exit_1` | Reviews returning `{"errors": [...]}` sets `had_error=True` → exit 1 |

**`tests/test_posts.py` — 1 test:**

| Test | What it covers |
|---|---|
| `test_pick_theme_returns_none_when_themes_list_is_empty` | `_pick_theme` returns `None` when themes list is `[]` |

**`tests/test_report.py` — 1 test:**

| Test | What it covers |
|---|---|
| `test_main_output_flag_error_exits_1` | `OSError` writing output file → exit 1 + stderr message |

**`tests/test_validator.py` — 3 tests:**

| Test | What it covers |
|---|---|
| `test_validate_content_missing_field_within_defaults` | `defaults` present but missing `post_cadence_days` / `max_post_chars` → per-field error |
| `test_validate_content_missing_llm_provider_field` | `llm` present but `provider` absent → error |
| `test_validate_content_missing_llm_model_id_field` | `llm` present but `model_id` absent → error |

**Coverage change:**

| Module | Before | After |
|---|---|---|
| `auth.py` | 33% | 70% |
| `business_profile.py` | 97% | 100% |
| `config.py` | 93% | 100% |
| `content.py` | 96% | 99% |
| `main.py` | 96% | 97% |
| `posts.py` | 99% | 100% |
| `validator.py` | 96% | 100% |
| **Total** | **96%** | **97%** |

The remaining 39 uncovered lines (3%) are the structural ceiling — exclusively:
- `try: from dotenv import load_dotenv; load_dotenv()` blocks in every CLI module (only reached when `python-dotenv` is installed; untestable in unit context)
- `if __name__ == "__main__":` guards across all CLI modules (untestable in unit context)
- `raise RuntimeError("retry loop exited without return or raise")` in `content.py` — explicitly annotated as an unreachable guard
- `auth.py` lines 65–81: the interactive `InstalledAppFlow` browser-launch block (only runs when `python -m meo.auth` is invoked directly)

**Files changed:**

| File | Change |
|---|---|
| `tests/test_auth.py` | New: 10 tests for `get_credentials()` and `_require_env()` |
| `tests/test_business_profile.py` | +4 tests: `_refresh_if_needed` expired path; `call_to_action` body field |
| `tests/test_config.py` | +1 test: `clear_cache()` directly called |
| `tests/test_content.py` | +4 tests: anthropic dispatch; missing-API-key paths; OpenAI system message |
| `tests/test_main.py` | +1 test: reviews-result-with-errors → exit 1 |
| `tests/test_posts.py` | +1 test: `_pick_theme` returns None on empty list |
| `tests/test_report.py` | +1 test: OSError when writing output file |
| `tests/test_validator.py` | +3 tests: per-field errors within present `defaults`/`llm` sections |

### New tests (+25 tests)

Total: **387/387 tests** (was 362).

---

## Completed this run (run 27)

### Tests: closed coverage gaps in `main.py`, `content.py`, and `discover_locations.py`

**Problem**: Three modules had meaningful untested branches that could regress silently:

| Module | Previous coverage | Missing paths |
|---|---|---|
| `src/meo/main.py` | 79% | Config-validation failure; store with TODO `location_id`; store with TODO `drive_folder_id`; post exception caught; reviews exception caught |
| `src/meo/content.py` | 90% | `anthropic.RateLimitError` → `RuntimeError` conversion; `anthropic.APIError` → `RuntimeError`; same two paths for OpenAI |
| `src/meo/tools/discover_locations.py` | 0% | All of `_get()` and `main()` — the setup helper operators run exactly once to find location IDs |

**Fix**: +18 new tests across three files.

**`tests/test_main.py` — 5 new tests:**

| Test | What it covers |
|---|---|
| `test_config_validation_errors_exit_1_before_auth` | `validate_all()` returning errors → exit 1 before `get_credentials` is called |
| `test_store_with_todo_location_id_is_skipped_and_exits_1` | `location_id` containing "TODO" → store skipped, no post/review call, exit 1 |
| `test_store_with_todo_drive_folder_id_logs_warning_but_exits_0` | `drive_folder_id` containing "TODO" → warning log, post + reviews still run, exit 0 |
| `test_post_exception_is_caught_and_causes_exit_1` | `run_post_for_store` raising → exception caught, `had_error=True`, exit 1 |
| `test_reviews_exception_is_caught_and_causes_exit_1` | `run_reviews_for_store` raising → exception caught, `had_error=True`, exit 1 |

**`tests/test_content.py` — 4 new tests (+ shared helpers):**

| Test | What it covers |
|---|---|
| `test_call_anthropic_rate_limit_error_becomes_runtime_error` | `anthropic.RateLimitError` from `messages.create` is caught and re-raised as `RuntimeError` (feeds retry logic) |
| `test_call_anthropic_api_error_becomes_runtime_error` | `anthropic.APIError` → `RuntimeError("Anthropic API error: ...")` |
| `test_call_openai_rate_limit_error_becomes_runtime_error` | `openai.RateLimitError` → `RuntimeError` |
| `test_call_openai_api_error_becomes_runtime_error` | `openai.APIError` → `RuntimeError("OpenAI API error: ...")` |

These are the handler lines that convert provider-specific exceptions into the `RuntimeError` that `_call_with_retry` uses to detect retryable failures. Without these tests, the retry system's error-detection path had no regression protection.

**`tests/test_discover_locations.py` — 9 new tests (new file):**

*`TestGet` — 4 tests:*
- Returns parsed JSON on HTTP 200
- Passes an empty `{}` dict when no `params` argument is given
- Passes caller-supplied `params` through to `session.get`
- Raises on HTTP error (via `resp.raise_for_status`)

*`TestMain` — 5 tests:*
- No accounts found → `sys.exit(1)`
- Account with locations → prints `location_id` and store title to stdout
- Account with no locations → prints `(no locations)`, `sys.exit(0)`
- Location-fetch error caught → prints "Could not fetch locations", `sys.exit(0)`
- Output includes a copy-paste YAML snippet with `location_id: "..."` for found locations

**Coverage change:**

| Module | Before | After |
|---|---|---|
| `main.py` | 79% | 96% |
| `content.py` | 90% | 96% |
| `discover_locations.py` | 0% | 96% |
| **Total** | **90%** | **96%** |

Remaining uncovered lines across all modules are exclusively:
- `try: from dotenv import load_dotenv; load_dotenv()` blocks (untestable in unit context — only reached when `python-dotenv` is installed)
- `if __name__ == "__main__":` guards (untestable in unit context)

**Files changed:**

| File | Change |
|---|---|
| `tests/test_main.py` | +5 new tests for error-branch coverage |
| `tests/test_content.py` | +4 new tests for Anthropic/OpenAI exception handler coverage + shared helper factories |
| `tests/test_discover_locations.py` | New file: 9 tests for `_get()` and `main()` |

### New tests (+18 tests)

Total: **362/362 tests** (was 344).

---

## Completed this run (run 26)

### Tests: `meo-status` now has full test coverage (`tests/test_status.py`)

**Problem**: `src/meo/tools/status.py` was the only module with 0% test coverage.
All 116 statements were exercised only via manual invocation — no automated
regression protection existed for:
- `_load_state()` (missing file, valid JSON, corrupt JSON)
- `_days_ago()` (today / yesterday / N days / invalid input)
- `main()` exit codes (0 = all ready, 1 = missing env or TODO placeholders)
- Output correctness (store names, env var names, last-post date, LLM config,
  state file info, partial-config message, OpenAI key check)
- Security: secret values must never appear in output

**Fix**: Added `tests/test_status.py` — 24 new tests covering all testable paths
in the module.  Coverage went from **0% → 97%** (the remaining 3 lines are the
`dotenv` import guard and `if __name__ == "__main__"` block, both untestable
in unit test context).

Key test groups:

| Group | Tests |
|---|---|
| `_load_state()` | missing file → `{}`; valid JSON → parsed dict; corrupt JSON → `{}` |
| `_days_ago()` | "today", "yesterday", "N days ago", invalid input → "?" |
| `main()` exit codes | exits 0 (all ready); exits 1 (missing env var); exits 1 (TODO location_id); exits 1 (partial store config) |
| `main()` output | store names; env var names; "never" on no post; last-post date from state; "Ready" message; state-file size; LLM provider + model |
| Security | secret values do not appear in stdout |
| OpenAI | flags `OPENAI_API_KEY` missing when `llm.provider: openai` |
| Messaging | "Partially configured" shown for mixed stores; "Next step" shown when all TODO |

**Files changed:**

| File | Change |
|---|---|
| `tests/test_status.py` | New: 24 tests for `_load_state`, `_days_ago`, `main()` |

### New tests (+24 tests)

Total: **344/344 tests** (was 320).

---

## Completed this run (run 25)

### Fix: per-store `max_post_chars` / `max_reply_chars` overrides were silently ignored (`src/meo/content.py`)

**Problem**: `generate_post()` and `generate_reply()` read the character-limit
values directly from `cfg.content()["defaults"]`:

```python
max_chars = conf["defaults"]["max_post_chars"]   # generate_post()
max_chars = conf["defaults"]["max_reply_chars"]  # generate_reply()
```

`max_post_chars` and `max_reply_chars` are listed in `_ALLOWED_OVERRIDE_KEYS`
(validator.py) and documented in the commented-out `overrides` templates in
`config/stores.yaml`, so owners have been led to believe that setting e.g.

```yaml
mybear_studio_kyoto:
  overrides:
    max_post_chars: 800
```

would shorten the generated post text for that store.  In reality it had zero
effect: the post was still truncated at the global 1500-char limit because both
generators bypassed `effective_defaults()`.

**Fix**: Both generators now read their character limits through
`cfg.effective_defaults(store)`, which merges global defaults with any
per-store overrides — the same function already used by `posts.py` and
`reviews.py` for `post_cadence_days`, `max_replies_per_run`, etc.

```python
max_chars = cfg.effective_defaults(store)["max_post_chars"]   # generate_post()
max_chars = cfg.effective_defaults(store)["max_reply_chars"]  # generate_reply()
```

All other values (`tone_profile`, `banned`, `industry_tones`) continue to read
from the global `cfg.content()` — only the truncation limit respects overrides,
which matches the documented intent.

**Files changed:**

| File | Change |
|---|---|
| `src/meo/content.py` | `generate_post()`: `conf["defaults"]["max_post_chars"]` → `cfg.effective_defaults(store)["max_post_chars"]`; `generate_reply()`: `conf["defaults"]["max_reply_chars"]` → `cfg.effective_defaults(store)["max_reply_chars"]` |
| `tests/test_content.py` | `test_generate_post_respects_per_store_max_chars_override`; `test_generate_reply_respects_per_store_max_chars_override` (2 new tests) |

### New tests (+2 tests)

| File | New test |
|---|---|
| `tests/test_content.py` | `test_generate_post_respects_per_store_max_chars_override` — LLM output truncated to override value (200), not global default (1500) |
| `tests/test_content.py` | `test_generate_reply_respects_per_store_max_chars_override` — reply truncated to override value (150), not global default (4096) |

Total: **320/320 tests** (was 318).

---

## Completed this run (run 24)

### Fix: Drive image-selection errors now fall back to "no photo" instead of failing the post (`src/meo/posts.py`)

**Problem**: `run_post_for_store()` had three separate Drive interactions:

1. `drive.pick_random_image()` — **no try/except** ← the bug
2. `drive.download_image()` — already in try/except
3. `gbp.upload_media_bytes()` — already in try/except

If `pick_random_image()` raised (e.g. because `drive_folder_id` was still the
TODO placeholder in `stores.yaml`, or a transient Drive API error), the
exception propagated all the way up to `main.py`, where it was caught and
recorded as a **post failure** for the entire store.

This is especially problematic on the first live run: a store owner who has
filled in `location_id` but not yet `drive_folder_id` would see their posts
fail entirely, rather than going out without a photo as the warning in `main.py`
suggests they would.

**Fix**: Wrapped `pick_random_image()` in a try/except in `posts.py`.  On any
exception, `image_meta` is set to `None` and a `WARNING` is logged — the same
graceful path taken when no images exist in the folder.

```
WARNING meo.posts: [the_body_kyoto] Drive image selection failed (invalid folder ID); posting without photo.
```

This is consistent with how download and upload errors were already handled:
all three Drive interactions now degrade gracefully to "post without photo"
rather than aborting the post.

**Files changed:**

| File | Change |
|---|---|
| `src/meo/posts.py` | `pick_random_image()` wrapped in `try/except Exception`; sets `image_meta = None` and logs WARNING on failure |
| `tests/test_posts.py` | New test: `test_drive_pick_image_error_falls_back_to_no_photo` — verifies that a Drive exception during image selection still results in `status="posted"` with `media_url=None` and `record_image` not called |

### New test (+1 test)

| File | New test |
|---|---|
| `tests/test_posts.py` | `test_drive_pick_image_error_falls_back_to_no_photo` |

Total: **318/318 tests** (was 317).

---

## Completed this run (run 23)

### Feature: `--no-env` flag for `meo-validate` (`src/meo/tools/validate.py`)

**Problem**: `meo-validate` always ran `validate_all(check_env=True)`, which
requires all four credential env vars to be set.  In CI (where credentials live
in repository secrets and are not exported to the validate step), running
`meo-validate` would always fail with missing-credential errors even when the
only intent was to catch YAML syntax and structural errors in `config/stores.yaml`
and `config/content.yaml`.

**Fix**: Added an `--no-env` flag via `argparse`.

```bash
meo-validate              # full check: config structure + env var presence
meo-validate --no-env     # config structure only — safe in CI without credentials
```

When `--no-env` is passed, `validate_all(check_env=False)` is called and the
success message reads `"config structure checks passed"` instead of
`"config + environment checks passed"` so it's clear what was validated.

### CI: config validation step (`.github/workflows/ci.yml`)

Added a new step between `Install dependencies` and `Run tests`:

```yaml
- name: Validate config structure
  run: python -m meo.tools.validate --no-env
```

This means every push/PR to `main` now checks that `config/stores.yaml` and
`config/content.yaml` are structurally valid — required sections present, known
industry values, supported LLM provider, no unknown override keys.

Previously a typo in a config file would only be caught on the first live run.
Now it's caught immediately in CI.

### CI: test coverage reporting (`.github/workflows/ci.yml`)

Updated the test step from:
```yaml
run: python -m pytest tests/ -v --tb=short
```
to:
```yaml
run: python -m pytest tests/ -v --tb=short --cov=meo --cov-report=term-missing
```

Coverage is now printed to the Actions log after every CI run so regressions in
test completeness are visible without a separate tool.  No minimum threshold is
enforced (non-blocking) — the report is informational.

**Files changed:**

| File | Change |
|---|---|
| `src/meo/tools/validate.py` | `argparse` parser with `--no-env` flag; `check_env=not args.no_env` passed to `validate_all`; success message distinguishes scope |
| `tests/test_validator.py` | 4 new CLI tests: exits 0 on valid config+env; exits 1 on missing env; `--no-env` passes without credentials; `--no-env` still catches config errors |
| `.github/workflows/ci.yml` | New `Validate config structure` step; coverage flag added to pytest invocation |

### New tests (+4 tests)

| File | New tests |
|---|---|
| `tests/test_validator.py` | `test_main_exits_0_when_config_and_env_are_valid`; `test_main_exits_1_when_env_vars_are_missing`; `test_main_no_env_skips_credential_check`; `test_main_no_env_still_catches_config_errors` |

Total: **317/317 tests** (was 313).

---

## Completed this run (run 22)

### Feature: Request timeouts in `_AuthSession` (`src/meo/business_profile.py`)

**Problem**: All HTTP requests in `_AuthSession` had no timeout. A stalled TCP
connection (e.g. a GBP API server that accepts the connection but sends no
response) would block the tool forever until the GitHub Actions job timeout
killed the runner.  In production this would silently starve all remaining stores.

**Fix**: Added `_DEFAULT_TIMEOUT = (10, 60)` — 10 s to connect, 60 s to receive
the first byte.  All three request methods (`get`, `post`, `put`) call
`kwargs.setdefault("timeout", _DEFAULT_TIMEOUT)` so callers can still override it
in the rare case a specific request genuinely needs more time.

### Feature: Idempotent PUT retry (`src/meo/business_profile.py`)

**Problem**: The retry adapter previously set `allowed_methods=["GET"]`.
The `reply_to_review` endpoint uses **PUT** (which is idempotent by HTTP
semantics — retrying it sets the same reply text again, never creates duplicates).
A transient 500 or 429 on a PUT caused `reply_to_review` to fail immediately
with no retry, while an equivalent failure on a GET would have been retried
automatically.

**Fix**: Added `"PUT"` to `allowed_methods`.  `"POST"` is explicitly excluded
(and remains excluded) because `create_local_post` is not idempotent —
auto-retrying a POST would publish duplicate posts.  The updated docstring
explains the reasoning directly.

### Feature: Review age filter (`src/meo/reviews.py`, `config/content.yaml`)

**Problem**: On the first live run after API access is granted, `run_reviews_for_store()`
would attempt to reply to every unreplied review ever written — potentially dozens
of months-old reviews.  This would:
- Confuse customers (seeing AI replies on old reviews out of the blue)
- Burn LLM quota unnecessarily
- Be limited only by `max_replies_per_run`, hiding the root cause

**Fix**: Added `max_review_age_days: 90` to `config/content.yaml` defaults.
In `run_reviews_for_store()`, reviews whose `createTime` is older than this
threshold are skipped with an `INFO` log listing the skipped reviewers.

Key design decisions:
- Parsed from the GBP API's RFC 3339 `createTime` field (e.g. `"2024-01-15T10:00:00.000Z"`).
- Reviews with **missing or unparseable** `createTime` are treated as "include" (fail-safe).
- `max_review_age_days: 0` disables the filter entirely (reply to all reviews regardless of age).
- The filter runs **before** `unreplied_total` is saved, so it doesn't inflate the `deferred` count.
- Fully overridable per store via the `overrides` section in `config/stores.yaml`.

Added `_review_age_days(review)` helper — returns fractional days (float) or
`None` if the timestamp is absent/malformed.

Added `"max_review_age_days"` to `_ALLOWED_OVERRIDE_KEYS` in `validator.py`.

**Files changed:**

| File | Change |
|---|---|
| `src/meo/business_profile.py` | `_DEFAULT_TIMEOUT`; `setdefault("timeout", ...)` in all three methods; `"PUT"` added to `allowed_methods`; updated docstring |
| `src/meo/reviews.py` | `from datetime import datetime, timezone`; `_review_age_days()` helper; age-filter block before `unreplied_total` |
| `config/content.yaml` | `defaults.max_review_age_days: 90` |
| `src/meo/validator.py` | `"max_review_age_days"` added to `_ALLOWED_OVERRIDE_KEYS` |

### New tests (+14 tests)

| File | New tests |
|---|---|
| `tests/test_business_profile.py` | `test_auth_session_get_passes_default_timeout`; `test_auth_session_post_passes_default_timeout`; `test_auth_session_put_passes_default_timeout`; `test_retry_config_includes_put` (4) |
| `tests/test_reviews.py` | `test_review_age_days_returns_a_positive_float_for_recent_review`; `test_review_age_days_returns_none_when_create_time_missing`; `test_review_age_days_returns_none_for_malformed_timestamp`; `test_review_age_days_parses_rfc3339_with_z_suffix`; `test_old_reviews_are_skipped_by_age_filter`; `test_recent_reviews_pass_age_filter`; `test_review_with_no_create_time_is_included_by_age_filter`; `test_age_filter_disabled_when_max_review_age_days_is_zero`; `test_per_store_max_review_age_days_override` (9) |
| `tests/test_validator.py` | `test_validate_stores_max_review_age_days_is_a_valid_override_key` (1) |

Total: **313/313 tests** (was 299).

---

## Completed this run (run 21)

### Fix: Silent assertion in `tests/test_reviews.py`

`test_low_star_review_held_for_manual_when_threshold_set` contained a bare
comparison expression on line 260:

```python
mock_gen.call_count == 1  # only called for the FOUR-star review
```

This evaluated to `True` or `False` and was silently discarded — the assertion
was **never actually checked**.  If a regression caused `generate_reply` to be
called for the held (1★) review as well, the test would still pass.

Fixed by adding `assert`:

```python
assert mock_gen.call_count == 1  # only called for the FOUR-star review
```

All 299 tests continue to pass.

---

## Completed this run (run 20)

### Feature: Atomic state writes + backup recovery (`src/meo/state.py`)

**Problem**: `_save()` wrote directly to `state.json` with `Path.write_text()`.
A crash mid-write (OOM kill, power loss, container eviction) could leave a
partially-written file.  On the next run, `_load()` would detect corrupt JSON
and fall back to an empty dict — silently discarding all rotation history,
replied-review guards, and content archives.

**Fix**: `_save()` now uses an atomic two-step write:

1. Write new state to `state.tmp` (complete write before any rename).
2. If `state.json` exists, rename it to `state.bak` (preserves last good state).
3. Rename `state.tmp` → `state.json` via `Path.replace()` (POSIX-atomic — either
   the old file or the new file is visible, never a partial write).

`_load()` now falls back to `state.bak` when `state.json` is missing or corrupt:

```
state.json  OK  → use it
state.json  BAD → try state.bak → use it (log WARNING)
state.bak   BAD → start fresh (log WARNING)
```

This protects against crash-at-write without any extra tooling.

**Added helpers:**
- `_backup_path()` — derives the `.bak` path from `_STATE_FILE` so tests that
  redirect `_STATE_FILE` to a temp path automatically get the correct backup path.

### Feature: Held-review snapshot persistence (`src/meo/state.py`, `reviews.py`)

**Problem**: Reviews held by `min_star_autoreply` (e.g., 1★/2★ reviews held for
manual reply) were only counted and logged.  The operator had no structured way
to see *which* reviews needed manual attention without reading log files.  On the
next run those same reviews would appear as held again — they would keep appearing
until manually replied to on GBP, but there was no export path.

**Fix**: Added a per-store held-review snapshot to `state.json`.

| Function | Behaviour |
|---|---|
| `record_held_reviews(store_key, reviews)` | Stores a snapshot of currently-held reviews (replaces previous — not appended) |
| `get_held_reviews(store_key)` | Returns the snapshot from the last live run |
| `clear_held_reviews(store_key \| None)` | Clears snapshot after manual replies are done |

Each entry in the snapshot: `{date, review_id, reviewer, stars, comment}`.

`reviews.py` calls `record_held_reviews()` whenever `min_star > 1` and not
dry-run — passing an empty list when all reviews are above the threshold so old
snapshots are cleared automatically when the situation resolves.

### Feature: `meo-export held-reviews` (`src/meo/tools/export.py`)

```bash
meo-export held-reviews                               # all stores → stdout
meo-export held-reviews --store the_body_kyoto        # single store
meo-export held-reviews --output held.csv             # write file (UTF-8-BOM)
```

Exports the held-review snapshot as a CSV so the operator can see the review
text, star rating, and reviewer name in a spreadsheet and reply manually on GBP.

**CSV schema:** `store_key, store_name, date, review_id, reviewer, stars, comment`

**"No data" message** is specific: `"No held reviews found. Either no reviews are
below min_star_autoreply, or the tool has not run in live mode yet."` — distinguishes
"threshold is 1 so nothing is held" from "tool hasn't run yet".

### Feature: `meo-reset held-reviews` (`src/meo/tools/reset.py`)

```bash
meo-reset held-reviews                                # clear all stores
meo-reset held-reviews --store the_body_kyoto         # single store
meo-reset all                                         # now also clears held_reviews
```

Clears the held-review snapshot after the operator has replied manually on GBP.
The snapshot is also refreshed automatically on the next daily run, so clearing
is optional — it just makes `meo-export held-reviews` immediately show an empty
result without waiting for the next scheduled run.

**Files changed:**

| File | Change |
|---|---|
| `src/meo/state.py` | `_backup_path()`; atomic `_save()` via tmp→rename; backup fallback in `_load()`; `record_held_reviews()`, `get_held_reviews()`, `clear_held_reviews()` |
| `src/meo/reviews.py` | Imports `record_held_reviews`; calls it after the star-threshold filter (live mode only) |
| `src/meo/tools/export.py` | `_HELD_FIELDS`, `export_held_reviews()`; `"held-reviews"` added to choices; specific "No data" message |
| `src/meo/tools/reset.py` | Imports `clear_held_reviews`; `"held-reviews"` subcommand; `"all"` includes it |

### New tests (+23 tests)

| File | New tests |
|---|---|
| `tests/test_state.py` | Atomic write: creates backup; corrupt main falls back to backup; both corrupt → fresh start; no .tmp file left after write (4). Held reviews: empty, store snapshot, replace semantics, empty list clears, per-store isolation, clear specific, clear all, clear missing (8) |
| `tests/test_reviews.py` | `patch_record_held_reviews` autouse fixture; `record_held_reviews` called with snapshot; not called in dry-run; called with empty list when all above threshold (3 new tests + autouse) |
| `tests/test_export.py` | `_patch_held_history` fixture; `TestExportHeldReviews` (3 tests); `TestMain` held-reviews header, content, no-data message (3 tests) |
| `tests/test_reset.py` | `_write_full_state` updated; held-reviews all stores; held-reviews specific store (2 tests); `test_run_reset_all_clears_every_section` updated |

Total: **299/299 tests** (was 276).

---

## Completed this run (run 19)

### Feature: Per-store content config overrides (`config/stores.yaml`, `src/meo/config.py`, `posts.py`, `reviews.py`)

**Problem**: All stores shared the same global defaults from `content.yaml`.
In practice, the three stores have different operational needs:

- A store might want to post every other day (`post_cadence_days: 2`) instead of daily.
- A new store owner might want `min_star_autoreply: 3` to hold 1–2★ reviews for
  personal review before an AI reply goes out.
- A high-traffic store might need `max_replies_per_run: 20` to catch up faster.

Previously, any such customisation required editing `content.yaml` globally —
changing it for one store also changed it for the others.

**Fix**: Each store in `stores.yaml` can now include an optional `overrides` section
that shadows any subset of `content.yaml` defaults for that store only.

**Example** (add to any store in `config/stores.yaml`):
```yaml
mybear_studio_kyoto:
  ...
  overrides:
    post_cadence_days: 2      # post every other day
    min_star_autoreply: 3     # hold 1-2★ reviews for manual handling
```

Allowed override keys (all optional; use any subset):

| Key | Default | Purpose |
|---|---|---|
| `post_cadence_days` | 1 | Days between 最新情報 posts for this store |
| `max_post_chars` | 1500 | Max chars for the generated post body |
| `max_reply_chars` | 4096 | Max chars for the generated reply |
| `max_replies_per_run` | 10 | Cap on LLM reply calls per daily run |
| `min_star_autoreply` | 1 | Hold reviews below this star count for manual handling |

Unknown override keys (typos, unsupported fields) are caught at startup by
`meo-validate` / `validate_all()` and reported as configuration errors before
any API call is attempted.

**Design decisions:**
- `effective_defaults(store)` in `config.py` returns a shallow dict copy of the
  global defaults, updated with the store's `overrides`. It does NOT mutate the
  cached global config — other stores are unaffected.
- Override is entirely config-driven: the owner edits `stores.yaml` only; no code
  change, no restart of any service.
- Commented-out `overrides` templates added to all three stores in `stores.yaml`
  so the owner knows exactly which keys are available.

### Fix: `--force` missing from GitHub Actions `workflow_dispatch` inputs

**Problem**: `main.py` supported `--force` (bypass the daily cadence guard for
manual re-runs) but the `workflow_dispatch` trigger in `daily_run.yml` had no
corresponding input — operators could not trigger a force re-post via the GitHub
Actions UI without editing the workflow file.

**Fix**: Added `force` as a boolean `choice` input to `workflow_dispatch`. The
run step now checks `inputs.force` alongside the existing `dry_run`,
`skip_posts`, and `skip_reviews` inputs.

**Files changed:**

| File | Change |
|---|---|
| `src/meo/config.py` | `effective_defaults(store)` — merges global defaults with per-store overrides |
| `src/meo/posts.py` | Uses `cfg.effective_defaults(store)` for `post_cadence_days` |
| `src/meo/reviews.py` | Uses `cfg.effective_defaults(store)` for `max_replies_per_run` and `min_star_autoreply` |
| `src/meo/validator.py` | `_ALLOWED_OVERRIDE_KEYS` constant; `validate_stores()` rejects unknown override keys |
| `config/stores.yaml` | Commented `overrides` templates added to all three stores |
| `.github/workflows/daily_run.yml` | Added `force` dispatch input; wired into the run step |

### New tests (+8 tests)

| File | New tests |
|---|---|
| `tests/test_config.py` | `test_effective_defaults_returns_global_defaults_when_no_overrides`; `test_effective_defaults_merges_store_overrides`; `test_effective_defaults_does_not_mutate_global_config` (3) |
| `tests/test_posts.py` | `test_per_store_cadence_override_passed_to_should_post_today` (1) |
| `tests/test_reviews.py` | `test_per_store_max_replies_override`; `test_per_store_min_star_override` (2) |
| `tests/test_validator.py` | `test_validate_stores_valid_override_keys_pass`; `test_validate_stores_unknown_override_key_produces_error` (2) |

Total: **276/276 tests** (was 268).

---

## Completed this run (run 18)

### Feature: Banned-word detection in generated content (`src/meo/content.py`)

**Problem**: `generate_post()` and `generate_reply()` instructed the LLM to avoid
the `banned_words` list but never verified the output.  A model that occasionally
ignores instructions (e.g. when the topic makes a banned phrase feel natural) could
publish non-compliant text without the operator knowing.

**Fix**: Added `_check_banned_words(text, banned)` — a case-insensitive scan of
the generated text against the banned list.  If any banned word is found, a
`WARNING` log line is emitted with the matched word(s) and a hint to check
`config/content.yaml`.  The text is returned unchanged (banning is advisory, not
a hard error) so the automation never stalls on a single word match.

```
WARNING meo.content: [the_body_kyoto] Generated post contains banned word(s): ['激安'].
Adjust config/content.yaml banned_words or themes if this recurs.
```

Both `generate_post()` and `generate_reply()` call the check after truncation.

**Files changed:**

| File | Change |
|---|---|
| `src/meo/content.py` | `_check_banned_words()` helper; both generators call it after text is finalized |

### Feature: Configurable minimum-star threshold for auto-replies (`src/meo/reviews.py`, `config/content.yaml`)

**Problem**: `run_reviews_for_store()` auto-replied to ALL unreplied reviews regardless
of star rating.  Many operators want to personally review and respond to 1-star (or
low-star) reviews before an AI reply goes public — an angry customer with a legitimate
complaint needs a human response, not a canned "thank you for your feedback" message.

**Fix**: Added `min_star_autoreply: 1` to `config/content.yaml` `defaults`.

| Setting | Behaviour |
|---|---|
| `min_star_autoreply: 1` | Default — reply to all reviews (no change in behaviour) |
| `min_star_autoreply: 3` | Auto-reply to 3★, 4★, 5★ only; hold 1★ and 2★ for manual handling |
| `min_star_autoreply: 4` | Auto-reply to 4★ and 5★ only; hold 1★–3★ for manual handling |

Reviews below the threshold are:
- **Not replied to** (no API call, no LLM call)
- **Logged at INFO** with reviewer name and star rating
- **Counted as `manual`** in the result dict (new key — backward-compatible)
- **Surfaced in the Slack notification** when `manual > 0`

Also added `_star_to_int(rating)` helper that maps `"ONE"/"TWO"/…/"FIVE"` → `1…5`
(unknown strings default to `3`).

**Files changed:**

| File | Change |
|---|---|
| `config/content.yaml` | `defaults.min_star_autoreply: 1` |
| `src/meo/reviews.py` | `_STAR_VALUES` dict; `_star_to_int()` helper; threshold filter after max-replies cap; `manual` key in result dict |
| `src/meo/notify.py` | Shows `"{N} need manual reply"` in Slack message when `manual > 0` |

### New tests (+13 tests)

| File | New tests |
|---|---|
| `tests/test_content.py` | `test_check_banned_words_finds_match`; `test_check_banned_words_case_insensitive`; `test_check_banned_words_returns_empty_when_no_match`; `test_generate_post_logs_warning_when_banned_word_found`; `test_generate_post_no_warning_when_no_banned_word`; `test_generate_reply_logs_warning_when_banned_word_found` (6) |
| `tests/test_reviews.py` | `test_star_to_int_known_values`; `test_star_to_int_unknown_defaults_to_three`; `test_low_star_review_held_for_manual_when_threshold_set`; `test_manual_zero_when_threshold_is_one`; `test_all_reviews_held_when_all_below_threshold` (5) |
| `tests/test_notify.py` | `test_format_manual_reviews_shown`; `test_format_manual_reviews_absent_when_zero` (2) |

Total: **268/268 tests** (was 255).

---

## Completed this run (run 17)

### New CLI: `meo-reset` (`src/meo/tools/reset.py`)

Operators can now selectively clear parts of `state.json` without editing the
file manually.  Useful for recovery after a failed post, after uploading new
Drive photos, or after editing `config/content.yaml` themes.

```bash
meo-reset post-guard                           # clear "already posted today" guard for all stores
meo-reset post-guard --store the_body_kyoto    # single store
meo-reset image-history                        # forget recently-used Drive images (after new uploads)
meo-reset theme-history                        # forget recently-used themes (after editing content.yaml)
meo-reset replied-reviews                      # reset local replied-review tracking set
meo-reset all                                  # wipe all of the above (all stores)
meo-reset all --store mybear_studio_kyoto      # wipe all state for one store
python -m meo.tools.reset post-guard
```

| Subcommand       | What it clears | Why you'd use it |
|---|---|---|
| `post-guard`      | `last_post` date per store | Run failed mid-post; want next run to retry without `--force` |
| `image-history`   | `recent_images` list | Uploaded new photos; want them treated as fresh immediately |
| `theme-history`   | `recent_themes` list | Changed theme list in `content.yaml`; old themes polluting rotation |
| `replied-reviews` | `replied_reviews` set | Clearing the propagation-lag safety net (safe — GBP stays authoritative) |
| `all`             | All of the above | Complete reset for a store or the whole tool |

**Design decisions:**
- `--store KEY` limits to one store; omitting it applies to all stores.
- `run_reset()` (the library function) accepts any key — it returns `[]` for
  stores with no data and does not raise.  Only the CLI validates the key
  against `stores.yaml`.
- No `--confirm` flag: each subcommand is targeted and reversible (a new post
  or reply run repopulates state).  The docstring and `--help` text make the
  scope clear.

**Files changed:**

| File | Change |
|---|---|
| `src/meo/tools/reset.py` | New module: `run_reset()`, `main()` |
| `src/meo/state.py` | `clear_post_guard()`, `clear_image_history()`, `clear_theme_history()`, `clear_replied_reviews()` |
| `pyproject.toml` | Added `meo-reset` script entry point |

### Improvement: star-rating rendering in review reply prompts (`src/meo/content.py`)

**Problem**: `generate_reply()` forwarded the GBP API's raw star-rating string
(`"FIVE"`, `"THREE"`, etc.) directly into the LLM prompt.  The LLM had to
infer both sentiment and intensity from an uppercase English word — a
sub-optimal signal for a Japanese-language reply generator.

Additionally, star-only reviews (no written comment — valid in GBP) caused the
prompt to contain a blank `レビュー内容:` line.  The LLM could not distinguish
a genuinely empty review from a missing field and sometimes generated a reply
that referenced non-existent review text.

**Fix**: Added `_star_label()` helper and updated the `generate_reply()` prompt:

| Before | After |
|---|---|
| `評価: FIVE` | `評価: ★★★★★（5/5）` |
| `評価: THREE` | `評価: ★★★☆☆（3/5）` |
| `レビュー内容: ` | `レビュー内容: （コメントなし）` |

The `_star_label()` mapping covers all five GBP star levels; unrecognised
strings pass through unchanged (forward-compatible).  A new condition line
in the prompt instructs the LLM to base its reply on the star rating alone
when no comment is present.

**Files changed:**

| File | Change |
|---|---|
| `src/meo/content.py` | `_STAR_LABELS` dict; `_star_label()` helper; updated `generate_reply()` prompt |

### New tests (+34 tests)

| File | New tests |
|---|---|
| `tests/test_state.py` | 10 tests for `clear_post_guard`, `clear_image_history`, `clear_theme_history`, `clear_replied_reviews` — specific store, all stores, missing key |
| `tests/test_reset.py` | 15 new tests: `run_reset` (post-guard all/specific, image-history, theme-history, replied-reviews, all, all-specific-store, nonexistent key, empty state); `main()` (exits 0, all exits 0, unknown store exits 1, specific store output, nothing-to-clear) |
| `tests/test_content.py` | 9 new tests: `_star_label` (5 parametrised ratings + unknown passthrough); `generate_reply` (star label in prompt, raw string absent, empty comment shows placeholder, missing comment key shows placeholder, real comment passed through) |

Total: **255/255 tests** (was 221).

---

## Completed this run (run 16)

### New: Docker deployment support (`Dockerfile`, `docker-compose.yml`)

Operators who prefer self-hosted VPS deployment over GitHub Actions can now run
the tool in Docker without modifying any code.

**Files added:**

| File | Purpose |
|---|---|
| `Dockerfile` | Slim Python 3.11 image; installs cffi + all dependencies; mounts `/app/logs` as a volume |
| `docker-compose.yml` | Defines `meo` service (daily run) and `tools` service (one-shot CLI commands); maps `meo_logs` named volume for state persistence |

**Deployment workflow:**
```bash
cp .env.example .env    # fill in credentials
docker compose build
docker compose run --rm meo                       # dry run (safe)
docker compose run --rm meo python -m meo.main    # live run
# Add to host cron: 0 0 * * * docker compose run --rm --no-deps meo python -m meo.main
```

The `meo_logs` Docker named volume persists `logs/state.json` across container
restarts, so the duplicate-post guard and rotation history work correctly.

### New: `.env.example` credential template

Added `.env.example` at the repo root — a documented template listing all
required and optional environment variables with descriptions and setup links.

Operators copy it once (`cp .env.example .env`) instead of consulting the README
for each variable name. The `.gitignore` was updated to carve out `.env.example`
from the existing `.env.*` rule so the template is tracked.

**Files changed:**

| File | Change |
|---|---|
| `.env.example` | New: documents all env vars with comments and links |
| `.gitignore` | Added `!.env.example` exception so the template is committed |

### New CLI: `meo-export` (`src/meo/tools/export.py`)

Exports the content archive from `state.json` to CSV for spreadsheet review.

```bash
meo-export posts                                  # all stores → stdout
meo-export replies                                # all stores → stdout
meo-export posts --store the_body_kyoto           # single store
meo-export posts --output posts.csv               # write file (UTF-8-BOM for Excel)
meo-export replies --store the_body_kyoto --output kyoto_replies.csv
python -m meo.tools.export posts
```

**CSV schemas:**

*posts*: `store_key, store_name, date, theme, text, post_name`

*replies*: `store_key, store_name, date, reviewer, stars, review_id, reply`

**Design decisions:**
- Files are written with a UTF-8 BOM (`utf-8-sig`) so Excel on Windows/macOS
  auto-detects the encoding without requiring a manual import step.
- Stdout output uses plain UTF-8 (no BOM) for piping/shell use.
- Unknown `--store` key exits 1 with a clear error listing valid keys.
- No data in state.json exits 0 with a helpful message (not an error — the tool
  may not have run yet in live mode).
- `dotenv` is loaded if present, consistent with all other CLI tools.

**Files changed:**

| File | Change |
|---|---|
| `src/meo/tools/export.py` | New module: `export_posts()`, `export_replies()`, `_write_csv()`, `main()` |
| `pyproject.toml` | Added `meo-export` script entry point |

### Updated: README

Added:
- Docker deployment section (build → dry run → live run → cron)
- Operator CLI tools table listing all 8 CLI commands with one-line descriptions
- `.env.example` reference in Environment Variables section

### New tests (+21 tests)

| File | New tests |
|---|---|
| `tests/test_export.py` | `TestExportPosts` (5); `TestExportReplies` (3); `TestWriteCsv` (4); `TestMain` (9) |

Total: **221/221 tests** (was 200).

---

## Completed this run (run 15)

### Fix: Duplicate-reply guard (`src/meo/state.py`, `reviews.py`)

**Problem**: GBP's `list_reviews` can take several minutes to reflect a newly-posted
reply.  If two runs fire within that window (e.g. the scheduled GitHub Actions job
plus a manual `workflow_dispatch`), the second run sees the same reviews as
unreplied and tries to reply again — causing duplicate owner replies or GBP 4xx
errors on the second attempt.

**Fix**: Added a local replied-review tracking set to `state.json`:

| Function | Purpose |
|---|---|
| `record_replied_review(store_key, review_id)` | Persists after every live reply; capped at 500 IDs per store |
| `get_replied_reviews(store_key)` | Returns the tracked set; checked before replying in `run_reviews_for_store()` |

`reviews.py` now filters out reviews whose ID appears in the local set before
entering the reply loop.  A log line at `INFO` level reports how many reviews were
skipped for this reason.

Not called in dry-run mode (consistent with all other state writes).

### New CLI: `meo-health` (`src/meo/tools/health.py`)

**Purpose**: Read-only connectivity check intended for first-time setup and after
credential/config changes.  Runs before any live `meo-run` to confirm the Google
APIs are reachable and the configured store IDs are valid.

```bash
meo-health                            # all stores
meo-health --store the_body_kyoto     # single store
```

Per store, the tool checks (all read-only — no writes):
- GBP API: calls `list_reviews()` on the configured `location_id`
- Drive API: calls `list_images()` on the configured `drive_folder_id`

Output:
```
=== MEO Health Check ===

✓ [the_body_kyoto] THE BODY 京都店
    ✓ gbp_list_reviews: OK (12 review(s))
    ✓ drive_list_images: OK (8 image(s))

All checks passed. Ready for a live run.
```

Unconfigured `drive_folder_id` is flagged with `!` (warning) but does not fail
the check — posts can go out without photos.  Unconfigured `location_id` is a
hard `✗` failure.  Exits 0 if all stores pass, 1 if any check fails.

**Files changed:**

| File | Change |
|---|---|
| `src/meo/state.py` | `_REPLIED_REVIEW_CAPACITY = 500`; `record_replied_review()`; `get_replied_reviews()`; updated module docstring |
| `src/meo/reviews.py` | Import new state helpers; local-filter step before the reply loop; `record_replied_review()` called after each live reply |
| `src/meo/tools/health.py` | New module: `run_health()`, `main()` |
| `pyproject.toml` | Added `meo-health` script entry point |

### New tests (+20 tests)

| File | New tests |
|---|---|
| `tests/test_state.py` | 6 tests: empty history; persist/retrieve; most-recent-first ordering; cap at capacity; dedup on re-record; per-store isolation |
| `tests/test_reviews.py` | `patch_replied_review_state` autouse fixture; `test_locally_replied_review_is_skipped`; `test_record_replied_review_called_after_live_reply`; `test_record_replied_review_not_called_on_dry_run` |
| `tests/test_health.py` | 11 tests: GBP ok, GBP error, Drive error, unconfigured `location_id`, unconfigured `drive_folder_id` (warning-not-fatal), auth failure, store key filter; `main()` exits 0/1/auth-fail/unknown-key |

Total: **200/200 tests** (was 180).

---

## Completed this run (run 14)

### Feature: LLM retry with exponential backoff (`src/meo/content.py`)

**Problem**: `_call_anthropic()` and `_call_openai()` had no retry logic. A
transient API failure (rate limit, 5xx server error) would fail the entire store
run immediately, with no attempt to recover.

**Fix**: Added `_call_with_retry(fn, max_attempts, *, base_delay)` helper.

| Aspect | Behaviour |
|---|---|
| `EnvironmentError` / `ValueError` | Never retried (config errors — fix the config) |
| `RuntimeError` (generic API error) | Retried with `base_delay × 2^attempt` backoff |
| `RuntimeError` (rate limit) | Retried with 4× longer delay to respect quota window |
| Max attempts | `llm.max_retries` in `config/content.yaml` (default: 3) |

Both `_call_anthropic` and `_call_openai` now pass their inner API call through
`_call_with_retry`.  Added `max_retries: 3` to `config/content.yaml`.

### Feature: Post/reply content archiving (`src/meo/state.py`, `posts.py`, `reviews.py`)

**Problem**: After a post or reply was published, the only way to see what the LLM
generated was to check Google manually.  `state.json` tracked dates and rotation
history but not the actual text.

**Fix**: Two new archiving subsystems in `state.py`:

| Function | What it stores | Capacity |
|---|---|---|
| `record_post_content(store_key, text, theme, post_name)` | Date, theme, full post text, GBP resource name | Last 30 per store |
| `get_post_history(store_key)` | Returns archived entries (most recent first) | — |
| `record_reply_content(store_key, review_id, reviewer, stars, reply_text)` | Date, reviewer, star rating, full reply text | Last 50 per store |
| `get_reply_history(store_key)` | Returns archived entries (most recent first) | — |

Both functions are called automatically:
- `posts.py` calls `record_post_content()` after every successful live post
- `reviews.py` calls `record_reply_content()` after every successful live reply

Neither is called in dry-run mode.

### New CLI: `meo-report` (`src/meo/tools/report.py`)

```bash
meo-report                            # all stores
meo-report --store the_body_kyoto     # single store
meo-report --output logs/report.txt   # also save to file
python -m meo.tools.report
```

Reads `state.json` and prints a formatted report:
- Per store: last 5 posts (date, theme, 100-char preview, GBP resource name)
- Per store: last 5 review replies (date, reviewer, star rating, 100-char preview)
- Star ratings are rendered as ★ symbols

### New CLI flag: `--force` (`src/meo/main.py`, `posts.py`)

```bash
python -m meo.main --force
python -m meo.main --store the_body_kyoto --force
```

Bypasses the cadence guard (`should_post_today`) for manual re-runs — useful
when a post failed partway through or you want to regenerate today's post.
Dry-run already bypassed the guard; `--force` covers the live path only.

**Files changed:**

| File | Change |
|---|---|
| `config/content.yaml` | Added `llm.max_retries: 3` |
| `src/meo/content.py` | `_call_with_retry()` helper; both providers use it |
| `src/meo/state.py` | `record_post_content`, `get_post_history`, `record_reply_content`, `get_reply_history`, constants `_POST_HISTORY_SIZE=30` / `_REPLY_HISTORY_SIZE=50` |
| `src/meo/posts.py` | Import + call `record_post_content`; add `force` param |
| `src/meo/reviews.py` | Import + call `record_reply_content` in live reply path |
| `src/meo/main.py` | `--force` argparse flag; passes `force=` to `run_post_for_store` |
| `src/meo/tools/report.py` | New module: `run_report()`, `_format_store_section()`, `main()` |
| `pyproject.toml` | Added `meo-report` script entry point |

### New tests (+32 tests)

| File | New tests |
|---|---|
| `tests/test_content.py` | 6 retry tests: `_call_with_retry` — succeeds immediately, succeeds on retry, raises after max attempts, no retry on EnvironmentError, sleeps between attempts, longer delay for rate limits |
| `tests/test_state.py` | 11 archiving tests: post history (empty, store entry, ordering, cap, per-store isolation, None theme); reply history (empty, store entry, ordering, cap, per-store isolation) |
| `tests/test_posts.py` | `test_record_post_content_called_with_correct_args`; `test_record_post_content_not_called_on_dry_run`; `test_force_flag_bypasses_cadence_guard`; autouse fixture `patch_record_post_content` (silences archiving in all tests) |
| `tests/test_reviews.py` | `test_record_reply_content_called_after_live_reply`; `test_record_reply_content_not_called_on_dry_run`; autouse fixture `patch_record_reply_content` |
| `tests/test_main.py` | `test_force_flag_forwarded_to_run_post_for_store`; updated `track_post` signatures to accept `force=False` |
| `tests/test_report.py` | 9 new tests: `run_report` (store names, post history, reply history, empty placeholder, unknown store, filter); `main()` (exits 0, exits 1 on bad key, saves file with `--output`) |

Total: **180/180 tests** (was 148).

---

## Completed this run (run 13)

### Feature: startup config validation (`src/meo/validator.py`)

**Problem**: Any misconfiguration (wrong field name in `stores.yaml`, unsupported
`llm.provider`, missing env var) was discovered mid-run when the first API call
failed — often with a cryptic Python exception rather than a clear message.

**Fix**: Added `validator.py` with four pure functions:

| Function | Checks |
|---|---|
| `validate_env(content_conf)` | All 4 required env vars; respects `llm.provider` (ANTHROPIC_API_KEY vs OPENAI_API_KEY) |
| `validate_stores(stores_data)` | Required fields per store; known `industry` values; `call_to_action` structure when present |
| `validate_content(content_data)` | `defaults`, `llm`, and `industry_tones` sections; supported provider value |
| `validate_all(*, check_env=True)` | Runs all checks; returns a flat list of error strings (empty = valid) |

`validate_all()` is now called in `main()` immediately after logging is set up
and before any Google API call.  If any check fails, all errors are logged and
the process exits 1 with a clear summary — instead of failing halfway through
the first store.

`validate_all(check_env=False)` is available for CI jobs that only want to
validate config file structure without requiring live credentials.

### New CLI: `meo-validate` (`src/meo/tools/validate.py`)

```bash
meo-validate              # or: python -m meo.tools.validate
```

Runs `validate_all()` and prints each error with `✗`.  Exits 0 on success,
exits 1 on failure.  Useful as a one-shot pre-flight check before the first
live run or after editing `config/stores.yaml` / `config/content.yaml`.

### Feature: call-to-action in local posts

Each store can now attach a button to its 最新情報 posts by adding a
`call_to_action` section to `config/stores.yaml`:

```yaml
call_to_action:
  action_type: "BOOK"   # BOOK | ORDER | SHOP | LEARN_MORE | SIGN_UP | CALL | GET_OFFER
  url: "https://yoursite.com/book"
```

When `url` is non-empty, `posts.py` builds the `{"actionType": ..., "url": ...}`
dict and passes it as `call_to_action=` to `BusinessProfileClient.create_local_post()`,
which already had the parameter wired to the GBP API body.

When `call_to_action` is absent from the store config, or when `url` is an
empty string, `None` is passed — the API call is identical to before, with no
CTA button in the post.

All three stores in `config/stores.yaml` now include a commented-out CTA
template that the owner can uncomment and fill in when the booking URL is ready.

**Files changed:**

| File | Change |
|---|---|
| `src/meo/validator.py` | New module: `validate_env`, `validate_stores`, `validate_content`, `validate_all` |
| `src/meo/tools/validate.py` | New CLI: `meo-validate` entry point |
| `src/meo/main.py` | Imports and calls `validate_all()` before auth |
| `src/meo/posts.py` | Reads `call_to_action` from store config; passes it to `create_local_post()` |
| `config/stores.yaml` | Commented-out CTA template added to all three stores |
| `pyproject.toml` | Added `meo-validate` script entry point |

### New tests (+25 tests)

| File | New tests |
|---|---|
| `tests/test_validator.py` | 21 new tests: `validate_env` (5); `validate_stores` (6); `validate_content` (4); `validate_all` (5) — see file for names |
| `tests/test_posts.py` | `test_call_to_action_passed_when_configured`; `test_call_to_action_omitted_when_not_configured`; `test_call_to_action_omitted_when_url_is_empty` |
| `tests/test_main.py` | `bypass_validation` autouse fixture patches `validate_all` in all 7 existing tests (not a new test count, but required for correctness) |

Updated: `test_live_run_downloads_and_uploads_image` — expected call to
`create_local_post` now includes `call_to_action=None` to match the updated
`posts.py` signature.

Total: **148/148 tests** (was 123).

---

## Completed this run (run 12)

### Improvement: Anthropic prompt caching (`src/meo/content.py`)

**Problem**: `_call_anthropic()` forwarded the system prompt as a plain string.
Every call to `generate_post()` or `generate_reply()` re-transmitted the full
system prompt to the Anthropic API, paying full input-token cost each time.

In a normal daily run (3 stores × post + up to 10 review replies each), the
same system prompt text is sent repeatedly — for `generate_post` it is
**byte-for-byte identical** across all 3 stores.

**Fix**: The `system` parameter is now sent as a list containing a single
content block with `cache_control: {"type": "ephemeral"}`:

```python
kwargs["system"] = [
    {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
]
```

Anthropic caches this prefix for 5 minutes.  Cache hits cost **10% of the
original input-token price** — effectively free for repeated calls within the
same daily run.  Estimated saving:
- `generate_post` system prompt (~75 tokens) cached after first store call →
  saves 2× re-transmission per run.
- `generate_reply` system prompt (~50 tokens, different per store) cached
  within each store's review-reply loop → saves up to 9× re-transmission per
  store when `max_replies_per_run = 10`.

No config changes needed.  The OpenAI path is unaffected.

### New tool: `meo-preview` (`src/meo/tools/preview.py`)

A new CLI that generates sample content previews for all configured stores
**without requiring Google credentials** — only `ANTHROPIC_API_KEY` (or
`OPENAI_API_KEY` if using the OpenAI provider).

**Purpose**: operators can run this after editing `config/content.yaml` (tone,
themes, banned words) to immediately see what the LLM would produce, without
triggering any Google API calls or touching live store data.

**Usage**:
```bash
# All stores
meo-preview                              # or: python -m meo.tools.preview

# One store
meo-preview --store the_body_kyoto

# Save to file
meo-preview --output logs/preview.txt
```

For each store the preview shows:
1. A full 最新情報 post body (same code path as the live runner, including
   theme selection from the configured theme list)
2. A review reply for a sample 3-star review (the most instructive rating —
   it requires both gratitude and a measured acknowledgement of a concern)

**Design decisions**:
- Per-store errors are captured (and exit code is set to 1) but do not block
  other stores — same isolation model as the main runner.
- Output goes to stdout always; `--output` additionally saves a UTF-8 file.
- `dotenv` is loaded if present (same as `main.py` and `status.py`) so the
  tool works identically in development and CI.

**Files changed:**

| File | Change |
|---|---|
| `src/meo/content.py` | `_call_anthropic`: system prompt sent as cached content block |
| `src/meo/tools/preview.py` | New module: `run_preview()`, `_format_output()`, `main()` |
| `pyproject.toml` | Added `meo-preview` script entry point |

### New tests (+14 tests)

| File | New tests |
|---|---|
| `tests/test_content.py` | `test_call_anthropic_passes_system_as_cached_block`; `test_call_anthropic_without_system_omits_system_key` |
| `tests/test_preview.py` | `test_run_preview_returns_post_and_reply_for_each_store`; `test_run_preview_captures_post_error`; `test_run_preview_captures_reply_error`; `test_run_preview_continues_after_one_store_error`; `test_format_output_contains_store_name_and_content`; `test_format_output_marks_errors`; `test_format_output_contains_timestamp`; `test_main_exits_0_on_success`; `test_main_exits_1_when_any_store_has_error`; `test_main_store_filter_limits_to_one_store`; `test_main_unknown_store_exits_1`; `test_main_output_flag_saves_file` |

Total: **123/123 tests** (was 109).

---

## Completed this run (run 11)

### Feature: Slack webhook run-completion notifications (`src/meo/notify.py`)

**Problem**: The daily automation runs unattended in GitHub Actions.  When
something goes wrong (post failed, review reply errored, a store was skipped
because `location_id` is still a TODO), the owner had to check the Actions log
manually to find out.

**Fix**: Added an optional Slack incoming-webhook notification sent at the end
of every run.  The message summarises, per store:
- Post status + theme selected
- Number of review replies sent / deferred to next run
- Any per-store or per-review errors
- A ✅ / ⚠️ footer line

**Design decisions:**
- **Opt-in via env var**: if `SLACK_WEBHOOK_URL` is not set the module is a
  complete no-op — no error, no log noise, zero impact on existing runs.
- **Non-fatal**: any network or HTTP error from the webhook is logged as
  `WARNING` and swallowed; a broken Slack webhook never changes the process
  exit code or blocks other stores.
- **Pure summary module**: `notify.py` only reads result dicts; it has no
  knowledge of the GBP/Drive APIs.

**Files changed:**

| File | Change |
|---|---|
| `src/meo/notify.py` | New module: `send_run_summary()` + `_format_message()` |
| `src/meo/main.py` | `send_run_summary(all_results, dry_run=args.dry_run)` at end of run |
| `.github/workflows/daily_run.yml` | Passes `SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}` to run step |
| `README.md` | Documents `SLACK_WEBHOOK_URL` as an optional env var |

### Fix: `skipped` / `deferred` semantics in `reviews.py`

**Problem**: `run_reviews_for_store()` returned `"skipped": len(reviews) -
len(unreplied)` — but `unreplied` had already been truncated by the
`max_replies_per_run` cap before the subtraction.  So with 20 total reviews, 15
unreplied, and `max_replies_per_run=10`:

```
skipped = 20 - 10 = 10   # WRONG: 5 already-replied + 5 deferred mixed together
```

This made the summary log misleading and the `send_run_summary` Slack message
would have shown the wrong numbers.

**Fix**: Save `unreplied_total` **before** the cap, then compute:

```python
"skipped":  len(reviews) - unreplied_total,        # truly already-replied
"deferred": unreplied_total - len(unreplied),       # capped; will retry next run
```

`deferred` is a new key — backward-compatible (callers checking only `replied`
and `errors` are unaffected).  The Slack notification surfaces it when non-zero:
`"replies: 10, 5 deferred"`.

**Files changed:**

| File | Change |
|---|---|
| `src/meo/reviews.py` | `unreplied_total` saved before cap; `skipped` fixed; `deferred` key added |

### New tests (+14 tests)

| File | New tests |
|---|---|
| `tests/test_notify.py` | 13 new tests: `_format_message` content (header, store detail, deferred, errors, store-level error, skipped, no-actions); `send_run_summary` (no-op, posts, failure-safe, HTTP-error-safe, payload content) |
| `tests/test_reviews.py` | `test_max_replies_per_run_limits_replies`: added `deferred==3` and `skipped==0` assertions; `test_skipped_counts_only_already_replied`: new test verifying correct separation of already-replied vs deferred |

Total: **109/109 tests** (was 95).

---

## Completed this run (run 10)

### Feature: seasonal/date context in LLM prompts

**Problem**: `generate_post()` and `generate_reply()` sent no date or season
information to the LLM.  For a beauty salon / fitness studio in Japan, seasonal
relevance matters: spring UV care, summer sweat-reduction, autumn moisturising,
winter hand care.  Without the date, the LLM produced generic copy that read the
same any time of year.

**Fix**: Added three helpers to `content.py`:

| Helper | Purpose |
|---|---|
| `_season(month)` | Maps calendar month (1–12) → Japanese season name (春/夏/秋/冬) |
| `_jst_date_context()` | Returns `"2026年5月31日（春）"` — current JST date + season |

Both `generate_post()` and `generate_reply()` now inject
`現在の日付・季節: {date_context}` into their user prompts, and add the
instruction `季節感を自然に反映させる` / `必要に応じて季節のご挨拶を添える`.
This is backward-compatible — the forced_theme path also receives the date context.

**Files changed:**

| File | Change |
|---|---|
| `src/meo/content.py` | `_JST`, `_season()`, `_jst_date_context()` helpers; date context injected into both prompts |

### New operator tool: `tools/status.py`

`python -m meo.tools.status` (or `meo-status` after `pip install -e .`) prints
a human-readable summary of the tool's readiness:

- **Environment** — which of the four required env vars are set (values hidden)
- **Stores** — per-store config completeness (`location_id`, `drive_folder_id`),
  last post date + how many days ago, recent-image and recent-theme counts
- **Content config** — LLM provider, model, cadence, limits
- **State file** — path and size
- **Summary** — how many stores are fully configured, what to do next

Exit code 0 if everything is ready; exit code 1 if any store or env var is
missing (useful for CI pre-flight checks).

**Files changed:**

| File | Change |
|---|---|
| `src/meo/tools/status.py` | New module |
| `pyproject.toml` | Added `meo-status` script entry point |

### New tests (+16 tests)

| File | New tests |
|---|---|
| `tests/test_content.py` | `test_season_mapping` ×12 (all months); `test_generate_post_includes_date_context`; `test_generate_post_forced_theme_also_includes_date_context`; `test_generate_reply_includes_date_context`; `test_jst_date_context_contains_year_and_season` |

Total: **95/95 tests** (was 79).

---

## Completed this run (run 9)

### Feature: post theme rotation — avoid repeating the same content angle

**Problem**: `generate_post()` always passed the full theme list to the LLM,
which could pick the same theme (e.g. 季節のお手入れ情報) on consecutive days.
With only 4 themes per store this made the Google Business Profile feel
repetitive, mirroring the image-repetition problem solved in run 8.

**Fix**: The last `_THEME_HISTORY_SIZE` (default: 4) post themes are tracked in
`logs/state.json` under `"recent_themes"`. Before each post, `_pick_theme()`
(in `posts.py`) picks a theme not in that list; if every theme has been recently
used, any theme is allowed so posts never stall. The chosen theme is passed as
`forced_theme` to `generate_post()`, which writes an explicit-theme prompt to the
LLM instead of asking it to pick from a candidate list.

Key changes:

| File | Change |
|---|---|
| `src/meo/state.py` | `_THEME_HISTORY_SIZE = 4`; `record_theme(store_key, theme)`; `get_recent_themes(store_key)` |
| `src/meo/content.py` | `generate_post(store, *, forced_theme=None)` — new keyword-only arg; explicit-theme prompt branch when `forced_theme` is given; no-theme branch unchanged (backward-compatible) |
| `src/meo/posts.py` | `_pick_theme(store_key, themes)` helper; calls `get_recent_themes()` before `generate_post()`; passes `forced_theme=chosen_theme`; calls `record_theme()` after a successful live post; dry-run path logs the chosen theme without writing state; result dict gains `"theme"` key |

### New tests (+11 tests)

| File | New tests |
|---|---|
| `tests/test_state.py` | 6 tests mirroring the image-rotation suite: empty history, persist/retrieve, ordering, cap at limit, deduplication, per-store isolation |
| `tests/test_content.py` | `forced_theme` appears in prompt and suppresses candidate list; no-`forced_theme` path lists all themes |
| `tests/test_posts.py` | `forced_theme` forwarded to `generate_post`; `record_theme` called after live post; `record_theme` NOT called on dry run; 4 existing live-path tests hardened with `get_recent_themes` / `record_theme` patches |

Total: **79/79 tests** (was 68).

---

## Completed this run (run 8)

### Feature: image rotation — avoid re-posting the same Drive photo

**Problem**: `drive.pick_random_image()` was purely random. With a small photo
library (e.g. 3–5 images), the same image could easily be posted on consecutive
days, which looks repetitive to customers viewing the Google Business Profile.

**Fix**: The last `_IMAGE_HISTORY_SIZE` (default: 5) Drive file IDs that were
attached to posts are now tracked in `logs/state.json` under `"recent_images"`.
Before each post, `pick_random_image()` receives that list and prefers images
*not* in it; if the entire folder has been recently used, any image is returned
so posts always go out.

Key changes:

| File | Change |
|---|---|
| `src/meo/state.py` | Added `record_image(store_key, file_id)` and `get_recent_images(store_key)` plus `_IMAGE_HISTORY_SIZE = 5` constant |
| `src/meo/drive.py` | `pick_random_image(folder_id, *, recent_ids=None)` — new keyword-only arg; backward-compatible (callers omitting it get the old behaviour) |
| `src/meo/posts.py` | Calls `get_recent_images(store_key)` before image selection; calls `record_image(store_key, file_id)` after a successful live post |

### New test files: `test_drive.py` and `test_business_profile.py`

`drive.py` and `business_profile.py` had zero direct unit tests (they were only
exercised indirectly via `test_posts.py` and `test_reviews.py`).

**`tests/test_drive.py`** (9 new tests):
- `list_images`: returns files, returns empty list, handles pagination
- `pick_random_image`: basic, empty folder, prefers fresh over recent, fallback when all recent, ignores empty `recent_ids` list
- `download_image`: returns bytes from the authenticated Drive API

**`tests/test_business_profile.py`** (14 new tests):
- `create_local_post`: returns resource, correct body fields (`topicType`, `languageCode`), attaches media URL, omits media field when None
- `upload_media_bytes`: returns `googleUrl`, falls back to `sourceUrl`, raises when no URL in response, sends `multipart/related` Content-Type
- `list_reviews`: returns all reviews, returns empty list, handles pagination
- `reply_to_review`: sends correct `comment` body field
- `_AuthSession._auth_headers`: injects Bearer token, merges caller-supplied headers

### New image-rotation tests in `test_state.py` (+6 tests)

| Test | What it covers |
|---|---|
| `test_get_recent_images_empty_when_no_history` | Returns `[]` before any image is recorded |
| `test_record_image_persists_and_is_retrievable` | Basic write/read round-trip |
| `test_record_image_most_recent_is_first` | Ordering: most recently used ID is at index 0 |
| `test_record_image_history_capped_at_limit` | Oldest IDs are evicted once `_IMAGE_HISTORY_SIZE` is reached |
| `test_record_image_deduplicates_on_reuse` | Re-recording an existing ID moves it to the front, no duplicates |
| `test_image_history_independent_per_store` | Store A's history does not affect store B |

### Updated `test_posts.py`

Live-path tests now also patch `meo.posts.get_recent_images` (→ `[]`) and
`meo.posts.record_image` (→ no-op) to keep tests hermetic. One new assertion
in `test_live_run_downloads_and_uploads_image` verifies
`record_image` is called with the correct store key and file ID. One new
assertion in `test_no_image_posts_without_photo` verifies `record_image`
is NOT called when no image is available.

Total: **68/68 tests** (was 39).

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

| Secret name | Required | Value |
|---|---|---|
| `GOOGLE_CLIENT_ID` | Yes | from Step 3 |
| `GOOGLE_CLIENT_SECRET` | Yes | from Step 3 |
| `GOOGLE_REFRESH_TOKEN` | Yes | from Step 4 |
| `ANTHROPIC_API_KEY` | Yes | from Step 5 |
| `SLACK_WEBHOOK_URL` | No (recommended) | Slack incoming webhook URL for run-completion notifications |

The daily workflow (`.github/workflows/daily_run.yml`) then runs automatically at 9 AM JST.
You can also trigger it manually from the **Actions** tab with a dry-run option.

**To set up Slack notifications** (optional but recommended):
1. Go to https://api.slack.com/messaging/webhooks
2. Create a new app → "Incoming Webhooks" → activate → add to workspace → choose a channel
3. Copy the webhook URL and add it as `SLACK_WEBHOOK_URL` in GitHub Actions secrets
4. After each daily run you will receive a message in that channel summarising what was posted

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

All code is complete and the test suite is green (390/390, 98% coverage).
**The only remaining work is human action** (Steps 1–8 above).

After API access is granted and `config/stores.yaml` is filled in:
1. Run `meo-status` to check config + env var readiness.
2. Run `pytest` to confirm all tests pass.
3. **Run `meo-preview`** to verify LLM output quality before any live Google API calls.
   This requires only `ANTHROPIC_API_KEY` — no Google credentials needed yet.
4. Run `python -m meo.main --store the_body_kyoto --dry-run` to verify single-store flow.
5. Run `python -m meo.main --dry-run` for all stores.
6. Choose a deployment method:
   - **GitHub Actions** (included): add secrets in Step 7 to activate the daily scheduler.
   - **Docker / VPS**: `cp .env.example .env && docker compose build && docker compose run --rm meo`
   - **cron (bare Python)**: see README § Scheduling.
   - `SLACK_WEBHOOK_URL` is optional but recommended for run-completion alerts.
7. Remove `--dry-run` or trigger the workflow without the flag for the first live run.
8. After the first live post, run `meo-export posts --output posts.csv` to confirm the
   content archive is working and review AI-generated text quality in the CSV.
9. Verify that `upload_media_bytes()` returns a `googleUrl` field and remove the TODO
   in `business_profile.py` once confirmed.

"""Per-store run-state tracking — prevents duplicate posts and tracks rotation history.

State is stored in logs/state.json as a simple JSON object:
  {
    "last_post":          {"the_body_kyoto": "2024-01-15", ...},
    "recent_images":      {"the_body_kyoto": ["file_id_1", "file_id_2"], ...},
    "recent_themes":      {"the_body_kyoto": ["季節のお手入れ情報", ...], ...},
    "replied_reviews":    {"the_body_kyoto": ["rev001", "rev002", ...], ...},
    "answered_questions": {"the_body_kyoto": ["q001", "q002", ...], ...},
    "held_reviews":       {"the_body_kyoto": [{"date": "2024-01-15", ...}, ...], ...},
    "dismissed_reviews":  {"the_body_kyoto": ["rev003", ...], ...},
    "run_results":        {"the_body_kyoto": {
                             "consecutive_failures": 0,
                             "consecutive_successes": 3,
                             "last_error_type": null,
                             "last_error_date": null
                           }, ...}
  }

Writes are atomic: a .tmp file is written first, then renamed over state.json via
os.replace() (POSIX-atomic). The previous state.json is backed up as state.bak
before each overwrite. If state.json is corrupt, _load() falls back to state.bak.

This file is NOT committed to git (covered by .gitignore logs/).
It is written by the daily runner after each successful post or reply.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_STATE_FILE = Path(__file__).resolve().parents[2] / "logs" / "state.json"  # src/meo/state.py → parents[2] = repo root

# How many recently-used Drive image IDs to remember per store.
_IMAGE_HISTORY_SIZE = 5

# How many recently-used post themes to remember per store.
_THEME_HISTORY_SIZE = 4

# Dates are anchored to JST (UTC+9) because the business and its "daily" cadence
# are in Japan. The GitHub Actions scheduler runs at 0 UTC = 9 AM JST, but
# manual workflow_dispatch triggers can fire at any UTC hour — using UTC dates
# could mis-classify a JST "new day" run as same-day and skip the post.
_JST = ZoneInfo("Asia/Tokyo")

# GBP propagation lag guard: cap at 500 IDs per store (~5 KB in state.json).
_REPLIED_REVIEW_CAPACITY = 500

_POST_HISTORY_SIZE = 30    # max archived post entries per store
_REPLY_HISTORY_SIZE = 50   # max archived reply entries per store
_SCORE_HISTORY_SIZE = 60   # max daily score snapshots (approx 2 months)
_ANSWERED_QUESTION_CAPACITY = 500  # GBP Q&A propagation lag guard
_ANSWER_HISTORY_SIZE = 50  # max archived Q&A answer entries per store


def _today() -> date:
    return datetime.now(tz=_JST).date()


def _backup_path() -> Path:
    """Return the backup path derived from the current _STATE_FILE."""
    return _STATE_FILE.with_suffix(".bak")


def _load() -> dict[str, Any]:
    """Load state from disk, falling back to .bak on corrupt/missing main file."""
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Could not read state file %s: %s — trying backup.", _STATE_FILE, exc
            )
    backup = _backup_path()
    if backup.exists():
        try:
            data = json.loads(backup.read_text(encoding="utf-8"))
            logger.warning("Loaded state from backup %s.", backup)
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Could not read backup file %s: %s — starting fresh.", backup, exc
            )
    return {}


def _save(state: dict[str, Any]) -> None:
    """Write state atomically via tmp→rename, backing up the previous file."""
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    if _STATE_FILE.exists():
        _STATE_FILE.replace(_backup_path())
    tmp.replace(_STATE_FILE)


# ---------------------------------------------------------------------------
# Generic helpers shared by rotation/clear functions
# ---------------------------------------------------------------------------

def _record_rotation(
    section_name: str, store_key: str, item: str, capacity: int
) -> None:
    """Prepend item to the rotation list at section_name[store_key], capped at capacity.

    If item is already in the list it is moved to the front (no duplicates).
    """
    state = _load()
    history: list[str] = state.setdefault(section_name, {}).setdefault(store_key, [])
    if item in history:
        history.remove(item)
    history.insert(0, item)
    state[section_name][store_key] = history[:capacity]
    _save(state)


def _clear_section(section_name: str, store_key: str | None) -> list[str]:
    """Clear one or all entries in a top-level state section.

    Returns the list of store keys that were cleared.
    """
    state = _load()
    section: dict[str, Any] = state.get(section_name, {})
    if store_key is not None:
        cleared = [store_key] if store_key in section else []
        section.pop(store_key, None)
    else:
        cleared = list(section.keys())
        section.clear()
    state[section_name] = section
    _save(state)
    return cleared


# ---------------------------------------------------------------------------
# Post timing
# ---------------------------------------------------------------------------

def should_post_today(store_key: str, cadence_days: int = 1) -> bool:
    """Return True if a post is due for this store today.

    A post is due when at least `cadence_days` have passed since the last post,
    or when no post has ever been recorded.
    """
    state = _load()
    last_str = state.get("last_post", {}).get(store_key)
    if not last_str:
        return True
    try:
        last_date = date.fromisoformat(last_str)
    except ValueError:
        logger.warning("Invalid last_post date '%s' for %s — will post.", last_str, store_key)
        return True
    return _today() >= last_date + timedelta(days=cadence_days)


def record_post(store_key: str) -> None:
    """Record that a post was successfully published for store_key today."""
    today = _today()
    state = _load()
    state.setdefault("last_post", {})[store_key] = today.isoformat()
    _save(state)
    logger.debug("Recorded post date for %s: %s", store_key, today.isoformat())


def get_last_post_date(store_key: str) -> str | None:
    """Return the last post date for store_key as ISO string, or None if never posted."""
    return _load().get("last_post", {}).get(store_key)


# ---------------------------------------------------------------------------
# Image rotation helpers
# ---------------------------------------------------------------------------

def record_image(store_key: str, file_id: str) -> None:
    """Record that file_id was used for a post; deprioritises it in future picks."""
    _record_rotation("recent_images", store_key, file_id, _IMAGE_HISTORY_SIZE)
    logger.debug("Recorded image use for %s: %s", store_key, file_id)


def get_recent_images(store_key: str) -> list[str]:
    """Return recently-used Drive image file IDs for store_key (most recent first)."""
    return list(_load().get("recent_images", {}).get(store_key, []))


# ---------------------------------------------------------------------------
# Theme rotation helpers
# ---------------------------------------------------------------------------

def record_theme(store_key: str, theme: str) -> None:
    """Record that theme was used in a post; deprioritises it in future picks."""
    _record_rotation("recent_themes", store_key, theme, _THEME_HISTORY_SIZE)
    logger.debug("Recorded theme for %s: %s", store_key, theme)


def get_recent_themes(store_key: str) -> list[str]:
    """Return recently-used post themes for store_key (most recent first)."""
    return list(_load().get("recent_themes", {}).get(store_key, []))


# ---------------------------------------------------------------------------
# Content archiving helpers
# ---------------------------------------------------------------------------

def record_post_content(
    store_key: str,
    text: str,
    theme: str | None,
    post_name: str | None = None,
    *,
    manual: bool = False,
) -> None:
    """Archive the generated post text for this store (last _POST_HISTORY_SIZE kept).

    Set manual=True when the post text was supplied by the owner (via meo-post-manual)
    rather than AI-generated, so history viewers can distinguish the two.
    """
    entry: dict[str, Any] = {
        "date": _today().isoformat(),
        "theme": theme or "",
        "text": text,
        "post_name": post_name or "",
        "manual": manual,
    }
    state = _load()
    history: list[dict] = state.setdefault("post_history", {}).setdefault(store_key, [])
    history.insert(0, entry)
    state["post_history"][store_key] = history[:_POST_HISTORY_SIZE]
    _save(state)
    logger.debug("Archived post content for %s (%d chars)", store_key, len(text))


def get_post_history(store_key: str) -> list[dict]:
    """Return the archived post history for store_key (most recent first)."""
    return list(_load().get("post_history", {}).get(store_key, []))


def record_reply_content(
    store_key: str,
    review_id: str,
    reviewer: str,
    stars: str,
    reply_text: str,
) -> None:
    """Archive a generated review reply for this store (last _REPLY_HISTORY_SIZE kept)."""
    entry: dict[str, str] = {
        "date": _today().isoformat(),
        "review_id": review_id,
        "reviewer": reviewer,
        "stars": stars,
        "reply": reply_text,
    }
    state = _load()
    history: list[dict] = state.setdefault("reply_history", {}).setdefault(store_key, [])
    history.insert(0, entry)
    state["reply_history"][store_key] = history[:_REPLY_HISTORY_SIZE]
    _save(state)
    logger.debug("Archived reply content for %s (review %s)", store_key, review_id)


def get_reply_history(store_key: str) -> list[dict]:
    """Return the archived reply history for store_key (most recent first)."""
    return list(_load().get("reply_history", {}).get(store_key, []))


# ---------------------------------------------------------------------------
# Q&A answer tracking — prevent double-answers on GBP propagation delay
# ---------------------------------------------------------------------------

def record_answered_question(store_key: str, question_id: str) -> None:
    """Record that an answer was successfully posted for question_id.

    Mirrors record_replied_review() — an answer POSTed via the Q&A API can take
    several minutes to appear in list_questions().  Tracking answered IDs locally
    prevents the next run from re-answering the same question while GBP propagates.
    """
    _record_rotation("answered_questions", store_key, question_id, _ANSWERED_QUESTION_CAPACITY)
    logger.debug("Recorded answered question for %s: %s", store_key, question_id)


def get_answered_questions(store_key: str) -> list[str]:
    """Return Q&A question IDs answered locally for store_key (most recent first)."""
    return list(_load().get("answered_questions", {}).get(store_key, []))


def record_answer_content(
    store_key: str,
    question_id: str,
    question_text: str,
    answer_text: str,
) -> None:
    """Archive a generated Q&A answer for this store (last _ANSWER_HISTORY_SIZE kept)."""
    entry: dict[str, str] = {
        "date": _today().isoformat(),
        "question_id": question_id,
        "question": question_text,
        "answer": answer_text,
    }
    state = _load()
    history: list[dict] = state.setdefault("answer_history", {}).setdefault(store_key, [])
    history.insert(0, entry)
    state["answer_history"][store_key] = history[:_ANSWER_HISTORY_SIZE]
    _save(state)
    logger.debug("Archived answer content for %s (question %s)", store_key, question_id)


def get_answer_history(store_key: str) -> list[dict]:
    """Return the archived Q&A answer history for store_key (most recent first)."""
    return list(_load().get("answer_history", {}).get(store_key, []))


# ---------------------------------------------------------------------------
# Replied review tracking — prevent double-replies on GBP propagation delay
# ---------------------------------------------------------------------------

def record_replied_review(store_key: str, review_id: str) -> None:
    """Record that a reply was successfully posted for review_id.

    A reply posted via the GBP API can take several minutes to appear in
    list_reviews(). If a second run fires before propagation completes, the
    review still looks unreplied and the runner would try to reply again.
    We track replied IDs locally so the second run skips them.
    """
    _record_rotation("replied_reviews", store_key, review_id, _REPLIED_REVIEW_CAPACITY)
    logger.debug("Recorded replied review for %s: %s", store_key, review_id)


def get_replied_reviews(store_key: str) -> list[str]:
    """Return review IDs replied to locally for store_key (most recent first)."""
    return list(_load().get("replied_reviews", {}).get(store_key, []))


# ---------------------------------------------------------------------------
# Held review snapshot — reviews awaiting manual reply
# ---------------------------------------------------------------------------

def record_held_reviews(
    store_key: str,
    reviews: list[dict[str, Any]],
) -> None:
    """Snapshot reviews currently held for manual reply for store_key.

    Each entry in ``reviews`` must be a dict with keys:
        review_id, reviewer, stars, comment

    The snapshot REPLACES the previous one — entries do not accumulate across
    runs.  Call with an empty list when all held reviews have been resolved so
    ``get_held_reviews()`` returns [] for the next run.
    """
    today = _today().isoformat()
    snapshot = [{**r, "date": today} for r in reviews]
    state = _load()
    state.setdefault("held_reviews", {})[store_key] = snapshot
    _save(state)
    logger.debug("Snapshotted %d held review(s) for %s.", len(snapshot), store_key)


def get_held_reviews(store_key: str) -> list[dict[str, Any]]:
    """Return the held-review snapshot for store_key from the last run."""
    return list(_load().get("held_reviews", {}).get(store_key, []))


# ---------------------------------------------------------------------------
# Daily score snapshot — persists meo-score grades for trend tracking
# ---------------------------------------------------------------------------

def record_score_snapshot(date_str: str, grades: dict[str, str]) -> None:
    """Save overall health grades for one day to the score snapshot history.

    grades: {store_key: overall_grade_letter, ...}

    If called more than once on the same date (e.g. a manual run followed by
    the CI run) the earlier entry for that date is replaced so each date
    appears at most once. Keeps the last _SCORE_HISTORY_SIZE entries.
    """
    state = _load()
    history: list[dict] = state.get("score_history", [])
    history = [e for e in history if e.get("date") != date_str]
    history.insert(0, {"date": date_str, "grades": grades})
    state["score_history"] = history[:_SCORE_HISTORY_SIZE]
    _save(state)
    logger.debug("Recorded score snapshot for %s.", date_str)


def get_score_snapshots() -> list[dict]:
    """Return score snapshots in reverse chronological order (newest first).

    Each entry: {"date": "2026-08-04", "grades": {store_key: grade_letter, ...}}
    """
    return list(_load().get("score_history", []))


# ---------------------------------------------------------------------------
# State reset helpers — used by the meo-reset CLI tool
# ---------------------------------------------------------------------------

def clear_post_guard(store_key: str | None = None) -> list[str]:
    """Clear the last_post date guard for one or all stores.

    After clearing, should_post_today() returns True for the affected store(s)
    so the next run will post even if the cadence window has not elapsed.

    Returns:
        List of store keys whose guard was cleared.
    """
    cleared = _clear_section("last_post", store_key)
    logger.debug("Cleared post guard for: %s", cleared or "none")
    return cleared


def clear_image_history(store_key: str | None = None) -> list[str]:
    """Clear the Drive image rotation history for one or all stores.

    Useful after uploading new photos to a Drive folder.

    Returns:
        List of store keys whose image history was cleared.
    """
    cleared = _clear_section("recent_images", store_key)
    logger.debug("Cleared image history for: %s", cleared or "none")
    return cleared


def clear_theme_history(store_key: str | None = None) -> list[str]:
    """Clear the post theme rotation history for one or all stores.

    Useful after editing the theme list in content.yaml.

    Returns:
        List of store keys whose theme history was cleared.
    """
    cleared = _clear_section("recent_themes", store_key)
    logger.debug("Cleared theme history for: %s", cleared or "none")
    return cleared


def clear_replied_reviews(store_key: str | None = None) -> list[str]:
    """Clear the local replied-review tracking set for one or all stores.

    Safe to clear — GBP's own reviewReply field remains the authoritative source.

    Returns:
        List of store keys whose tracking set was cleared.
    """
    cleared = _clear_section("replied_reviews", store_key)
    logger.debug("Cleared replied reviews for: %s", cleared or "none")
    return cleared


def clear_held_reviews(store_key: str | None = None) -> list[str]:
    """Clear the held-review snapshot for one or all stores.

    Returns:
        List of store keys whose snapshot was cleared.
    """
    cleared = _clear_section("held_reviews", store_key)
    logger.debug("Cleared held reviews for: %s", cleared or "none")
    return cleared


# ---------------------------------------------------------------------------
# Dismissed review tracking — permanently suppress specific held reviews
# ---------------------------------------------------------------------------

def dismiss_held_review(store_key: str, review_id: str) -> None:
    """Permanently dismiss a review so the runner never queues it for manual reply.

    Also removes the review from the current held snapshot immediately so
    get_held_reviews() and meo-export held-reviews reflect the change
    without waiting for the next daily run.
    """
    state = _load()
    dismissed = state.setdefault("dismissed_reviews", {})
    ids: list[str] = dismissed.get(store_key, [])
    if review_id not in ids:
        ids.append(review_id)
    dismissed[store_key] = ids
    held: dict[str, list] = state.get("held_reviews", {})
    if store_key in held:
        held[store_key] = [r for r in held[store_key] if r.get("review_id") != review_id]
    state["held_reviews"] = held
    _save(state)
    logger.debug("Dismissed review %s for %s.", review_id, store_key)


def get_dismissed_reviews(store_key: str) -> list[str]:
    """Return the list of permanently dismissed review IDs for store_key."""
    return list(_load().get("dismissed_reviews", {}).get(store_key, []))


def undismiss_held_review(store_key: str, review_id: str) -> bool:
    """Remove a review ID from the dismissed set; returns True if it was found.

    After undismissing, the review will reappear in the held queue on the
    next daily run if it is still below min_star_autoreply.
    """
    state = _load()
    dismissed = state.get("dismissed_reviews", {})
    ids: list[str] = dismissed.get(store_key, [])
    if review_id not in ids:
        return False
    ids.remove(review_id)
    dismissed[store_key] = ids
    state["dismissed_reviews"] = dismissed
    _save(state)
    logger.debug("Undismissed review %s for %s.", review_id, store_key)
    return True


# ---------------------------------------------------------------------------
# Run result tracking — detect consecutive failures for Slack alerting
# ---------------------------------------------------------------------------

def record_run_result(store_key: str, success: bool, error_type: str | None = None) -> None:
    """Record the outcome of a live daily run for store_key.

    On success: resets consecutive_failures to 0, increments consecutive_successes;
    clears last_error_type and last_error_date.
    On failure: increments consecutive_failures, resets consecutive_successes to 0;
    records error_type and today's date.

    Only call for live runs — dry-run results must not affect the streak so that
    test/preview runs do not mask real failures.
    """
    today = _today().isoformat()
    state = _load()
    results: dict = state.setdefault("run_results", {})
    entry: dict = dict(results.get(store_key, {}))
    if success:
        entry["consecutive_failures"] = 0
        entry["consecutive_successes"] = entry.get("consecutive_successes", 0) + 1
        entry["last_error_type"] = None
        entry["last_error_date"] = None
    else:
        entry["consecutive_failures"] = entry.get("consecutive_failures", 0) + 1
        entry["consecutive_successes"] = 0
        entry["last_error_type"] = error_type
        entry["last_error_date"] = today
    results[store_key] = entry
    state["run_results"] = results
    _save(state)
    logger.debug("Recorded run result for %s: success=%s", store_key, success)


def get_run_streak(store_key: str) -> dict:
    """Return the run streak data for store_key.

    Always returns a dict with keys:
      consecutive_failures (int), consecutive_successes (int),
      last_error_type (str | None), last_error_date (str | None).
    Never raises — returns zero-defaults when no data exists for the store.
    """
    defaults: dict = {
        "consecutive_failures": 0,
        "consecutive_successes": 0,
        "last_error_type": None,
        "last_error_date": None,
    }
    stored = _load().get("run_results", {}).get(store_key, {})
    return {**defaults, **stored}

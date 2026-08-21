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

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# _STATE_FILE is defined here (not in _state_io.py) so test fixtures can patch
# it with monkeypatch.setattr(state_mod, "_STATE_FILE", tmp_path).
# _state_io.py functions resolve the path lazily via meo.state._STATE_FILE.
_STATE_FILE = Path(__file__).resolve().parents[2] / "logs" / "state.json"

# Private I/O infrastructure — shared with _state_reviews.py and _state_run.py.
from ._state_io import (  # noqa: E402
    _backup_path,  # noqa: F401 — re-exported for test patching
    _clear_section,
    _load,
    _record_rotation,
    _save,
    _today,
)

# Review tracking and run results live in dedicated sub-modules to stay
# within the 400-line cap; re-exported here so callers see one namespace.
from ._state_reviews import (  # noqa: F401
    clear_held_reviews,
    clear_replied_reviews,
    dismiss_held_review,
    get_dismissed_reviews,
    get_held_reviews,
    get_replied_reviews,
    record_held_reviews,
    record_replied_review,
    undismiss_held_review,
)
from ._state_run import get_run_streak, record_run_result  # noqa: F401

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# How many recently-used Drive image IDs to remember per store.
_IMAGE_HISTORY_SIZE = 5

# How many recently-used post themes to remember per store.
_THEME_HISTORY_SIZE = 4

_POST_HISTORY_SIZE = 30    # max archived post entries per store
_REPLY_HISTORY_SIZE = 50   # max archived reply entries per store
_SCORE_HISTORY_SIZE = 60   # max daily score snapshots (approx 2 months)
_ANSWERED_QUESTION_CAPACITY = 500  # GBP Q&A propagation lag guard
_ANSWER_HISTORY_SIZE = 50  # max archived Q&A answer entries per store
# GBP propagation lag guard: cap at 500 IDs per store (~5 KB in state.json).
_REPLIED_REVIEW_CAPACITY = 500


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

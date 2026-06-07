"""Per-store run-state tracking — prevents duplicate posts and tracks rotation history.

State is stored in logs/state.json as a simple JSON object:
  {
    "last_post":       {"the_body_kyoto": "2024-01-15", ...},
    "recent_images":   {"the_body_kyoto": ["file_id_1", "file_id_2"], ...},
    "recent_themes":   {"the_body_kyoto": ["季節のお手入れ情報", ...], ...},
    "replied_reviews": {"the_body_kyoto": ["rev001", "rev002", ...], ...}
  }

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

_STATE_FILE = Path(__file__).resolve().parents[3] / "logs" / "state.json"

# How many recently-used Drive image IDs to remember per store.
# Images in this list are deprioritised by drive.pick_random_image so that
# the same photo is not posted on consecutive days.
_IMAGE_HISTORY_SIZE = 5

# Dates are anchored to JST (UTC+9) because the business and its "daily" cadence
# are in Japan. The GitHub Actions scheduler runs at 0 UTC = 9 AM JST, but
# manual workflow_dispatch triggers can fire at any UTC hour — using UTC dates
# could mis-classify a JST "new day" run as same-day and skip the post.
_JST = ZoneInfo("Asia/Tokyo")


def _today() -> date:
    return datetime.now(tz=_JST).date()


def _load() -> dict[str, Any]:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read state file %s: %s — starting fresh.", _STATE_FILE, exc)
    return {}


def _save(state: dict[str, Any]) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


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


# ---------------------------------------------------------------------------
# Image rotation helpers
# ---------------------------------------------------------------------------

def record_image(store_key: str, file_id: str) -> None:
    """Record that file_id was used for a post for store_key.

    Keeps the most recent _IMAGE_HISTORY_SIZE IDs so drive.pick_random_image
    can avoid repeating the same photo on consecutive days.
    """
    state = _load()
    history: list[str] = (
        state.setdefault("recent_images", {}).setdefault(store_key, [])
    )
    if file_id in history:
        history.remove(file_id)
    history.insert(0, file_id)
    state["recent_images"][store_key] = history[:_IMAGE_HISTORY_SIZE]
    _save(state)
    logger.debug("Recorded image use for %s: %s", store_key, file_id)


def get_recent_images(store_key: str) -> list[str]:
    """Return recently-used Drive image file IDs for store_key (most recent first).

    Returns an empty list if no history exists.
    """
    return list(_load().get("recent_images", {}).get(store_key, []))


# ---------------------------------------------------------------------------
# Theme rotation helpers
# ---------------------------------------------------------------------------

# How many recently-used post themes to remember per store.
# Themes in this list are deprioritised by posts._pick_theme so that
# the same content angle is not repeated on consecutive posts.
_THEME_HISTORY_SIZE = 4


def record_theme(store_key: str, theme: str) -> None:
    """Record that theme was used in a post for store_key.

    Keeps the most recent _THEME_HISTORY_SIZE themes so posts._pick_theme
    can avoid repeating the same content angle on consecutive days.
    """
    state = _load()
    history: list[str] = (
        state.setdefault("recent_themes", {}).setdefault(store_key, [])
    )
    if theme in history:
        history.remove(theme)
    history.insert(0, theme)
    state["recent_themes"][store_key] = history[:_THEME_HISTORY_SIZE]
    _save(state)
    logger.debug("Recorded theme for %s: %s", store_key, theme)


def get_recent_themes(store_key: str) -> list[str]:
    """Return recently-used post themes for store_key (most recent first).

    Returns an empty list if no history exists.
    """
    return list(_load().get("recent_themes", {}).get(store_key, []))


# ---------------------------------------------------------------------------
# Content archiving helpers
# ---------------------------------------------------------------------------

_POST_HISTORY_SIZE = 30   # max archived post entries per store
_REPLY_HISTORY_SIZE = 50  # max archived reply entries per store


def record_post_content(
    store_key: str,
    text: str,
    theme: str | None,
    post_name: str | None = None,
) -> None:
    """Archive the generated post text for this store.

    Keeps the most recent _POST_HISTORY_SIZE entries so the owner can review
    what was published via `meo-report` without visiting Google manually.
    """
    entry: dict[str, str] = {
        "date": _today().isoformat(),
        "theme": theme or "",
        "text": text,
        "post_name": post_name or "",
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
    """Archive a generated review reply for this store.

    Keeps the most recent _REPLY_HISTORY_SIZE entries so the owner can review
    what was replied via `meo-report` without visiting Google manually.
    """
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
# Replied review tracking — prevent double-replies on GBP propagation delay
# ---------------------------------------------------------------------------

# A reply posted via the GBP API can take several minutes to appear in
# list_reviews(). If a second run fires before propagation completes, the
# review still looks unreplied and the runner would try to reply again.
# We track replied IDs locally so the second run skips them.
#
# 500 IDs × ~10 chars each ≈ 5 KB — well within JSON state file budget.
_REPLIED_REVIEW_CAPACITY = 500


def record_replied_review(store_key: str, review_id: str) -> None:
    """Record that a reply was successfully posted for review_id.

    Keeps the most recent _REPLIED_REVIEW_CAPACITY IDs so reviews.py can
    skip reviews that were replied to in a previous run before GBP propagation
    has updated the reviewReply field visible via list_reviews().
    """
    state = _load()
    history: list[str] = (
        state.setdefault("replied_reviews", {}).setdefault(store_key, [])
    )
    if review_id in history:
        history.remove(review_id)
    history.insert(0, review_id)
    state["replied_reviews"][store_key] = history[:_REPLIED_REVIEW_CAPACITY]
    _save(state)
    logger.debug("Recorded replied review for %s: %s", store_key, review_id)


def get_replied_reviews(store_key: str) -> list[str]:
    """Return review IDs replied to locally for store_key (most recent first).

    Returns an empty list if no history exists.
    """
    return list(_load().get("replied_reviews", {}).get(store_key, []))


# ---------------------------------------------------------------------------
# State reset helpers — used by the meo-reset CLI tool
# ---------------------------------------------------------------------------

def clear_post_guard(store_key: str | None = None) -> list[str]:
    """Clear the last_post date guard for one or all stores.

    After clearing, should_post_today() returns True for the affected store(s)
    so the next run will post even if the cadence window has not elapsed.
    Useful after a failed live post or to force regeneration without --force.

    Args:
        store_key: Clear only this store's guard.  Clears all stores when None.

    Returns:
        List of store keys whose guard was cleared.
    """
    state = _load()
    section: dict[str, Any] = state.get("last_post", {})
    if store_key is not None:
        cleared = [store_key] if store_key in section else []
        section.pop(store_key, None)
    else:
        cleared = list(section.keys())
        section.clear()
    state["last_post"] = section
    _save(state)
    logger.debug("Cleared post guard for: %s", cleared or "none")
    return cleared


def clear_image_history(store_key: str | None = None) -> list[str]:
    """Clear the Drive image rotation history for one or all stores.

    Useful after uploading new photos to a Drive folder — old IDs in the
    rotation list would deprioritise the new images until they aged out.

    Args:
        store_key: Clear only this store's history.  Clears all when None.

    Returns:
        List of store keys whose image history was cleared.
    """
    state = _load()
    section: dict[str, Any] = state.get("recent_images", {})
    if store_key is not None:
        cleared = [store_key] if store_key in section else []
        section.pop(store_key, None)
    else:
        cleared = list(section.keys())
        section.clear()
    state["recent_images"] = section
    _save(state)
    logger.debug("Cleared image history for: %s", cleared or "none")
    return cleared


def clear_theme_history(store_key: str | None = None) -> list[str]:
    """Clear the post theme rotation history for one or all stores.

    Useful after editing the theme list in content.yaml — stale theme names
    in the rotation list could otherwise deprioritise the new ones.

    Args:
        store_key: Clear only this store's history.  Clears all when None.

    Returns:
        List of store keys whose theme history was cleared.
    """
    state = _load()
    section: dict[str, Any] = state.get("recent_themes", {})
    if store_key is not None:
        cleared = [store_key] if store_key in section else []
        section.pop(store_key, None)
    else:
        cleared = list(section.keys())
        section.clear()
    state["recent_themes"] = section
    _save(state)
    logger.debug("Cleared theme history for: %s", cleared or "none")
    return cleared


def clear_replied_reviews(store_key: str | None = None) -> list[str]:
    """Clear the local replied-review tracking set for one or all stores.

    The tracking set prevents double-replies during GBP propagation lag (the
    window between posting a reply and list_reviews() reflecting it).  Clearing
    it is safe — GBP's own reviewReply field remains the authoritative source.

    Args:
        store_key: Clear only this store's tracking set.  Clears all when None.

    Returns:
        List of store keys whose tracking set was cleared.
    """
    state = _load()
    section: dict[str, Any] = state.get("replied_reviews", {})
    if store_key is not None:
        cleared = [store_key] if store_key in section else []
        section.pop(store_key, None)
    else:
        cleared = list(section.keys())
        section.clear()
    state["replied_reviews"] = section
    _save(state)
    logger.debug("Cleared replied reviews for: %s", cleared or "none")
    return cleared

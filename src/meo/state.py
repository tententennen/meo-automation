"""Per-store run-state tracking — prevents duplicate posts and tracks rotation history.

State is stored in logs/state.json as a simple JSON object:
  {
    "last_post":     {"the_body_kyoto": "2024-01-15", ...},
    "recent_images": {"the_body_kyoto": ["file_id_1", "file_id_2"], ...},
    "recent_themes": {"the_body_kyoto": ["季節のお手入れ情報", ...], ...}
  }

This file is NOT committed to git (covered by .gitignore logs/).
It is written by the daily runner after each successful post.
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

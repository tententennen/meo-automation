"""Private I/O infrastructure for state.py — load, save, and rotation helpers.

Internal module — all functions are re-exported by state.py.

_STATE_FILE is NOT defined here. It lives in state.py so that test fixtures
can patch it with monkeypatch.setattr(state_mod, "_STATE_FILE", tmp_path).
All functions here resolve the path lazily via _get_state_file() so patches
on meo.state._STATE_FILE take effect at call time, not at import time.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Dates are anchored to JST (UTC+9) because the business and its "daily" cadence
# are in Japan. The GitHub Actions scheduler runs at 0 UTC = 9 AM JST, but
# manual workflow_dispatch triggers can fire at any UTC hour — using UTC dates
# could mis-classify a JST "new day" run as same-day and skip the post.
_JST = ZoneInfo("Asia/Tokyo")


def _get_state_file() -> Path:
    """Return the current state file path from state.py (lazy, test-patch-safe)."""
    import meo.state as _state  # lazy — avoids circular at module load time
    return _state._STATE_FILE


def _today() -> date:
    return datetime.now(tz=_JST).date()


def _backup_path() -> Path:
    """Return the backup path derived from the current state file."""
    return _get_state_file().with_suffix(".bak")


def _load() -> dict[str, Any]:
    """Load state from disk, falling back to .bak on corrupt/missing main file."""
    state_file = _get_state_file()
    if state_file.exists():
        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Could not read state file %s: %s — trying backup.", state_file, exc
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
    state_file = _get_state_file()
    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    if state_file.exists():
        state_file.replace(_backup_path())
    tmp.replace(state_file)


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

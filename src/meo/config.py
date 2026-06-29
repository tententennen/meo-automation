"""Load and expose typed configuration from config/stores.yaml and config/content.yaml."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[2]  # repo root (src/meo/config.py → meo-automation/)
_CONFIG_DIR = _ROOT / "config"


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=None)
def _stores_cached() -> dict[str, Any]:
    return _load(_CONFIG_DIR / "stores.yaml")["stores"]


@lru_cache(maxsize=None)
def _content_cached() -> dict[str, Any]:
    return _load(_CONFIG_DIR / "content.yaml")


def stores() -> dict[str, Any]:
    """Return the 'stores' mapping keyed by store slug."""
    return _stores_cached()


def content() -> dict[str, Any]:
    """Return the full content-generation config."""
    return _content_cached()


def store_list() -> list[dict[str, Any]]:
    """Return a flat list of store dicts, each enriched with its key."""
    return [{"key": k, **v} for k, v in stores().items()]


def effective_defaults(store: dict[str, Any]) -> dict[str, Any]:
    """Return the effective content defaults for this store.

    Merges global defaults from content.yaml with any per-store overrides
    defined in stores.yaml under the store's optional 'overrides' key.
    Per-store values shadow the global default for that store only.

    Allowed override keys: post_cadence_days, max_post_chars, max_reply_chars,
    max_replies_per_run, min_star_autoreply, max_review_age_days.

    Example entry in stores.yaml:
        mybear_studio_kyoto:
          overrides:
            post_cadence_days: 2      # post every other day
            min_star_autoreply: 3     # hold 1-2 star reviews for manual handling
    """
    base = dict(content()["defaults"])   # shallow copy — values are all scalars
    base.update(store.get("overrides") or {})
    return base


def clear_cache() -> None:
    """Invalidate the in-process config cache (useful in tests that swap config files)."""
    _stores_cached.cache_clear()
    _content_cached.cache_clear()

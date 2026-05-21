"""Load and expose typed configuration from config/stores.yaml and config/content.yaml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[2]  # repo root (src/meo/config.py → meo-automation/)
_CONFIG_DIR = _ROOT / "config"


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def stores() -> dict[str, Any]:
    """Return the 'stores' mapping keyed by store slug."""
    return _load(_CONFIG_DIR / "stores.yaml")["stores"]


def content() -> dict[str, Any]:
    """Return the full content-generation config."""
    return _load(_CONFIG_DIR / "content.yaml")


def store_list() -> list[dict[str, Any]]:
    """Return a flat list of store dicts, each enriched with its key."""
    return [{"key": k, **v} for k, v in stores().items()]

"""Operational status reporter — shows config completeness, env vars, and run state.

Usage:
    python -m meo.tools.status

Reads config/stores.yaml, config/content.yaml, and logs/state.json (if present).
Never prints secret values — only reports whether each env var is set or missing.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from meo import config as cfg

_JST = ZoneInfo("Asia/Tokyo")
_STATE_FILE = Path(__file__).resolve().parents[4] / "logs" / "state.json"

_REQUIRED_ENV_VARS = [
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REFRESH_TOKEN",
    "ANTHROPIC_API_KEY",
]

_CHECK = "✓"
_CROSS = "✗"
_WARN = "!"


def _load_state() -> dict:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _days_ago(iso_date_str: str) -> str:
    try:
        last = date.fromisoformat(iso_date_str)
        today = datetime.now(tz=_JST).date()
        delta = (today - last).days
        if delta == 0:
            return "today"
        if delta == 1:
            return "yesterday"
        return f"{delta} days ago"
    except ValueError:
        return "?"


def main() -> None:
    print("=== MEO Automation Status ===")
    print()

    # ---- Environment variables ----
    print("Environment:")
    env_ok = True
    for var in _REQUIRED_ENV_VARS:
        val = os.environ.get(var)
        if val:
            print(f"  {_CHECK} {var}")
        else:
            print(f"  {_CROSS} {var}  ← NOT SET")
            env_ok = False

    llm_provider = cfg.content().get("llm", {}).get("provider", "anthropic")
    if llm_provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
        print(f"  {_CROSS} OPENAI_API_KEY  ← NOT SET (required for openai provider)")
        env_ok = False
    print()

    # ---- Store config ----
    state = _load_state()
    last_posts = state.get("last_post", {})
    recent_images = state.get("recent_images", {})
    recent_themes = state.get("recent_themes", {})

    stores = cfg.store_list()
    stores_ready = 0

    print("Stores:")
    for store in stores:
        key = store["key"]
        name = store["name"]
        location_id = store.get("location_id", "")
        folder_id = store.get("drive_folder_id", "")

        loc_ok = "TODO" not in location_id and bool(location_id)
        folder_ok = "TODO" not in folder_id and bool(folder_id)

        loc_sym = _CHECK if loc_ok else _CROSS
        folder_sym = _CHECK if folder_ok else _WARN

        last_post_str = last_posts.get(key)
        last_post_disp = (
            f"{last_post_str} ({_days_ago(last_post_str)})" if last_post_str else "never"
        )
        img_count = len(recent_images.get(key, []))
        theme_count = len(recent_themes.get(key, []))

        print(f"  [{key}] {name}")
        print(f"    location_id:     {loc_sym} {location_id if loc_ok else 'TODO — run: python -m meo.tools.discover_locations'}")
        print(f"    drive_folder_id: {folder_sym} {folder_id if folder_ok else 'TODO — paste Google Drive folder ID'}")
        print(f"    last post:       {last_post_disp}")
        print(f"    recent images:   {img_count} tracked")
        print(f"    recent themes:   {theme_count} tracked")
        print()

        if loc_ok and folder_ok:
            stores_ready += 1

    # ---- LLM config ----
    llm_conf = cfg.content().get("llm", {})
    content_defaults = cfg.content().get("defaults", {})
    print("Content config:")
    print(f"  provider:           {llm_conf.get('provider', 'anthropic')}")
    print(f"  model_id:           {llm_conf.get('model_id', '?')}")
    print(f"  post_cadence_days:  {content_defaults.get('post_cadence_days', 1)}")
    print(f"  max_post_chars:     {content_defaults.get('max_post_chars', 1500)}")
    print(f"  max_replies_per_run:{content_defaults.get('max_replies_per_run', 10)}")
    print()

    # ---- State file ----
    if _STATE_FILE.exists():
        size = _STATE_FILE.stat().st_size
        print(f"State file: {_STATE_FILE}  ({size} bytes)")
    else:
        print(f"State file: not yet created (will appear after first live post)")
    print()

    # ---- Summary ----
    print("Summary:")
    env_line = f"  {_CHECK} All required env vars set" if env_ok else f"  {_CROSS} Missing env vars — set them before running"
    store_line = f"  {_CHECK} {stores_ready}/{len(stores)} stores fully configured"
    print(env_line)
    print(store_line)
    if stores_ready == 0:
        print()
        print("  Next step: fill in config/stores.yaml location IDs and Drive folder IDs.")
        print("  See PROGRESS.md § Needs Human Action for step-by-step instructions.")
    elif stores_ready < len(stores):
        print()
        print("  Partially configured — only stores with both IDs set will be processed.")
    else:
        print()
        if env_ok:
            print("  Ready for a live run. Test first with: python -m meo.main --dry-run")
        else:
            print("  Config complete but env vars missing — set them, then run: python -m meo.main --dry-run")

    sys.exit(0 if (env_ok and stores_ready == len(stores)) else 1)


if __name__ == "__main__":
    main()

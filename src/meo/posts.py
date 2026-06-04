"""Post 最新情報 (local posts) with an attached Drive photo, per store.

Image flow:
  1. Pick a random image from the store's Drive folder (metadata only).
  2. Download the image bytes via the authenticated Drive API.
  3. Upload the bytes to GBP media endpoint → receive a hosted googleUrl.
  4. Attach the googleUrl when creating the local post.

Step 3 avoids the need for Drive files to be publicly shared: we authenticate
to Drive, download privately, then re-host via GBP. If the GBP upload fails,
the webContentLink from Drive is tried as a fallback (works only for public files).
"""

from __future__ import annotations

import logging
import random
from typing import Any

from . import config as cfg
from .business_profile import BusinessProfileClient
from .content import generate_post
from .drive import DriveClient
from .state import (
    get_recent_images,
    get_recent_themes,
    record_image,
    record_post,
    record_post_content,
    record_theme,
    should_post_today,
)

logger = logging.getLogger(__name__)


def _pick_theme(store_key: str, themes: list[str]) -> str | None:
    """Pick a post theme, preferring ones not used in recent posts.

    Falls back to the full theme list when every theme has been recently used,
    so posts are never blocked even with small theme libraries.
    Returns None when themes is empty.
    """
    if not themes:
        return None
    recent = get_recent_themes(store_key)
    available = [t for t in themes if t not in recent]
    return random.choice(available if available else themes)


def run_post_for_store(
    store: dict[str, Any],
    gbp: BusinessProfileClient,
    drive: DriveClient,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Generate and publish one 最新情報 post for a single store.

    Skips posting if a post was already made within the configured cadence window
    (post_cadence_days in content.yaml) to prevent duplicates if the runner fires
    more than once in a day.  Pass force=True to bypass this guard.

    Args:
        store:   Store dict from config.store_list().
        gbp:     Authenticated BusinessProfileClient.
        drive:   Authenticated DriveClient.
        dry_run: If True, log what would happen but make no API writes.
        force:   If True, bypass the cadence guard and always post.

    Returns:
        A result dict with keys: store_key, status, post_name (or error).
        status is one of: "posted", "dry_run", "skipped".
    """
    store_key = store["key"]
    location_id = store["location_id"]
    folder_id = store["drive_folder_id"]

    cadence_days: int = cfg.content()["defaults"].get("post_cadence_days", 1)

    if not dry_run and not force and not should_post_today(store_key, cadence_days):
        logger.info(
            "[%s] Post already made within cadence window (%d day(s)). Skipping.",
            store_key, cadence_days,
        )
        return {"store_key": store_key, "status": "skipped"}

    # --- Theme selection (prefer themes not used recently) ---
    content_conf = cfg.content()
    industry = store.get("industry", "beauty_salon")
    tone_profile = content_conf["industry_tones"].get(
        industry, content_conf["industry_tones"]["beauty_salon"]
    )
    themes: list[str] = tone_profile.get("themes", [])
    chosen_theme = _pick_theme(store_key, themes)
    if chosen_theme:
        logger.info("[%s] Selected theme: %s", store_key, chosen_theme)

    logger.info("[%s] Generating post text...", store_key)
    post_text = generate_post(store, forced_theme=chosen_theme)
    logger.info("[%s] Post text (%d chars): %s", store_key, len(post_text), post_text[:80])

    # --- Image selection (prefer images not used recently) ---
    recent_image_ids = get_recent_images(store_key)
    image_meta = drive.pick_random_image(folder_id, recent_ids=recent_image_ids)
    media_url: str | None = None

    if image_meta:
        logger.info("[%s] Selected Drive image: %s", store_key, image_meta.get("name"))

        if not dry_run:
            file_id = image_meta["id"]
            mime_type = image_meta.get("mimeType", "image/jpeg")
            try:
                logger.info("[%s] Downloading image from Drive...", store_key)
                image_bytes = drive.download_image(file_id)
                media_url = gbp.upload_media_bytes(location_id, image_bytes, mime_type)
            except Exception as exc:
                # Fall back to webContentLink (works only if the Drive file is publicly shared).
                fallback = image_meta.get("webContentLink")
                if fallback:
                    logger.warning(
                        "[%s] Drive→GBP upload failed (%s); using webContentLink fallback.",
                        store_key, exc,
                    )
                    media_url = fallback
                else:
                    logger.warning(
                        "[%s] Drive→GBP upload failed (%s); no fallback URL. Posting without photo.",
                        store_key, exc,
                    )
    else:
        logger.warning("[%s] No images found in Drive folder; posting without photo.", store_key)

    # --- Call-to-action (optional per-store config) ---
    cta_conf = store.get("call_to_action")
    call_to_action: dict[str, str] | None = None
    if cta_conf and cta_conf.get("url"):
        call_to_action = {
            "actionType": cta_conf["action_type"],
            "url": cta_conf["url"],
        }

    # --- Dry run ---
    if dry_run:
        logger.info(
            "[%s] DRY RUN — would post:\n%s\nTheme: %s\nImage: %s\nCTA: %s",
            store_key,
            post_text,
            chosen_theme or "LLM choice",
            image_meta.get("name") if image_meta else "none",
            call_to_action or "none",
        )
        return {
            "store_key": store_key,
            "status": "dry_run",
            "post_text": post_text,
            "theme": chosen_theme,
            "call_to_action": call_to_action,
        }

    # --- Live post ---
    result = gbp.create_local_post(location_id, post_text, media_url, call_to_action=call_to_action)
    record_post(store_key)
    record_post_content(store_key, post_text, chosen_theme, result.get("name"))
    if image_meta:
        record_image(store_key, image_meta["id"])
    if chosen_theme:
        record_theme(store_key, chosen_theme)
    return {
        "store_key": store_key,
        "status": "posted",
        "post_name": result.get("name"),
        "theme": chosen_theme,
    }

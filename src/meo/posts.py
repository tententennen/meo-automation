"""Post 最新情報 (local posts) with an attached Drive photo, per store."""

from __future__ import annotations

import logging
from typing import Any

from .business_profile import BusinessProfileClient
from .content import generate_post
from .drive import DriveClient

logger = logging.getLogger(__name__)


def run_post_for_store(
    store: dict[str, Any],
    gbp: BusinessProfileClient,
    drive: DriveClient,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Generate and publish one 最新情報 post for a single store.

    Args:
        store:   Store dict from config.store_list().
        gbp:     Authenticated BusinessProfileClient.
        drive:   Authenticated DriveClient.
        dry_run: If True, log what would happen but make no API calls.

    Returns:
        A result dict with keys: store_key, status, post_name (or error).
    """
    store_key = store["key"]
    location_id = store["location_id"]
    folder_id = store["drive_folder_id"]

    logger.info("[%s] Generating post text...", store_key)
    post_text = generate_post(store)
    logger.info("[%s] Post text (%d chars): %s", store_key, len(post_text), post_text[:80])

    image_meta = drive.pick_random_image(folder_id)
    media_url: str | None = None
    if image_meta:
        # webContentLink is a direct download URL; publicly shared files work here.
        # TODO: if files are not publicly shared, upload bytes to GBP media endpoint instead.
        media_url = image_meta.get("webContentLink")
        logger.info("[%s] Attaching image: %s", store_key, image_meta.get("name"))
    else:
        logger.warning("[%s] No images found in Drive folder; posting without photo.", store_key)

    if dry_run:
        logger.info("[%s] DRY RUN — would post:\n%s\nImage URL: %s", store_key, post_text, media_url)
        return {"store_key": store_key, "status": "dry_run", "post_text": post_text}

    result = gbp.create_local_post(location_id, post_text, media_url)
    return {"store_key": store_key, "status": "posted", "post_name": result.get("name")}

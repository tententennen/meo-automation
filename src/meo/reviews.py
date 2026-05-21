"""Fetch unreplied reviews and post AI-generated replies, per store."""

from __future__ import annotations

import logging
from typing import Any

from .business_profile import BusinessProfileClient
from .content import generate_reply

logger = logging.getLogger(__name__)


def run_reviews_for_store(
    store: dict[str, Any],
    gbp: BusinessProfileClient,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Fetch all unreplied reviews for a store and reply to each.

    Args:
        store:   Store dict from config.store_list().
        gbp:     Authenticated BusinessProfileClient.
        dry_run: If True, log what would happen but post no replies.

    Returns:
        A result dict with keys: store_key, replied (count), skipped (count), errors.
    """
    store_key = store["key"]
    location_id = store["location_id"]

    logger.info("[%s] Fetching reviews...", store_key)
    reviews = gbp.list_reviews(location_id)
    unreplied = [r for r in reviews if not _has_reply(r)]
    logger.info("[%s] %d unreplied review(s) of %d total.", store_key, len(unreplied), len(reviews))

    replied = 0
    errors: list[str] = []

    for review in unreplied:
        review_id = _extract_review_id(review)
        reviewer = review.get("reviewer", {}).get("displayName", "unknown")
        logger.info("[%s] Generating reply for review by %s (id=%s)...", store_key, reviewer, review_id)

        try:
            reply_text = generate_reply(review, store)
            logger.info("[%s] Reply (%d chars): %s", store_key, len(reply_text), reply_text[:80])

            if dry_run:
                logger.info("[%s] DRY RUN — would reply to review %s:\n%s", store_key, review_id, reply_text)
            else:
                gbp.reply_to_review(location_id, review_id, reply_text)
            replied += 1
        except Exception as exc:
            msg = f"Failed to reply to review {review_id}: {exc}"
            logger.error("[%s] %s", store_key, msg)
            errors.append(msg)

    return {
        "store_key": store_key,
        "replied": replied,
        "skipped": len(reviews) - len(unreplied),
        "errors": errors,
    }


def _has_reply(review: dict[str, Any]) -> bool:
    """Return True if the review already has an owner reply."""
    reply = review.get("reviewReply")
    return bool(reply and reply.get("comment"))


def _extract_review_id(review: dict[str, Any]) -> str:
    """Extract the bare review ID from the full resource name.

    Resource name format: "accounts/{a}/locations/{l}/reviews/{review_id}"
    """
    name = review.get("reviewId") or review.get("name", "")
    return name.split("/")[-1]

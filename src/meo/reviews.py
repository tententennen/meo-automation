"""Fetch unreplied reviews and post AI-generated replies, per store."""

from __future__ import annotations

import logging
from typing import Any

from . import config as cfg
from .business_profile import BusinessProfileClient
from .content import generate_reply
from .state import get_replied_reviews, record_replied_review, record_reply_content

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
    gbp_skipped = len(reviews) - len(unreplied)  # reviews already replied on GBP

    # Skip reviews already handled locally — guards against GBP propagation lag.
    # A reply POSTed in a previous run may not yet appear in list_reviews(),
    # making those reviews look unreplied. Checking our local set prevents
    # double-replying when two runs fire within the same propagation window.
    locally_replied = set(get_replied_reviews(store_key))
    if locally_replied:
        before_local = len(unreplied)
        unreplied = [r for r in unreplied if _extract_review_id(r) not in locally_replied]
        local_skip = before_local - len(unreplied)
        if local_skip:
            logger.info(
                "[%s] %d review(s) skipped (replied locally, awaiting GBP propagation).",
                store_key, local_skip,
            )

    unreplied_total = len(unreplied)  # save before the cap so deferred is accurate
    logger.info("[%s] %d unreplied review(s) of %d total.", store_key, unreplied_total, len(reviews))

    max_replies: int = cfg.content()["defaults"].get("max_replies_per_run", 10)
    if unreplied_total > max_replies:
        logger.warning(
            "[%s] %d unreplied reviews found; capping at %d (max_replies_per_run). "
            "Remaining will be picked up in future runs.",
            store_key, unreplied_total, max_replies,
        )
        unreplied = unreplied[:max_replies]

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
                record_replied_review(store_key, review_id)
                record_reply_content(
                    store_key,
                    review_id,
                    reviewer,
                    review.get("starRating", ""),
                    reply_text,
                )
            replied += 1
        except Exception as exc:
            msg = f"Failed to reply to review {review_id}: {exc}"
            logger.error("[%s] %s", store_key, msg)
            errors.append(msg)

    return {
        "store_key": store_key,
        "replied": replied,
        "skipped": gbp_skipped,                       # already-replied on GBP
        "deferred": unreplied_total - len(unreplied), # capped by max_replies_per_run
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

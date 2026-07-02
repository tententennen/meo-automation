"""Fetch unreplied reviews and post AI-generated replies, per store."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from . import config as cfg
from .business_profile import BusinessProfileClient
from .content import generate_reply
from .state import (
    get_replied_reviews,
    record_held_reviews,
    record_replied_review,
    record_reply_content,
)

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

    # --- Age filter --- #
    # Skip reviews older than max_review_age_days to prevent mass-replying to
    # year-old reviews on the first run after API access is granted.
    # Default 90 days is generous enough to catch anything recent; set to 0 to
    # disable and reply to all unreplied reviews regardless of age.
    max_age_days: int = cfg.effective_defaults(store).get("max_review_age_days", 90)
    if max_age_days > 0:
        fresh, too_old = [], []
        for r in unreplied:
            age = _review_age_days(r)
            if age is not None and age > max_age_days:
                too_old.append(r)
            else:
                fresh.append(r)
        if too_old:
            logger.info(
                "[%s] %d review(s) skipped (older than max_review_age_days=%d): %s",
                store_key, len(too_old), max_age_days,
                [r.get("reviewer", {}).get("displayName", "?") for r in too_old],
            )
        unreplied = fresh

    unreplied_total = len(unreplied)  # save before the cap so deferred is accurate
    logger.info("[%s] %d unreplied review(s) of %d total.", store_key, unreplied_total, len(reviews))

    max_replies: int = cfg.effective_defaults(store).get("max_replies_per_run", 10)
    if unreplied_total > max_replies:
        logger.warning(
            "[%s] %d unreplied reviews found; capping at %d (max_replies_per_run). "
            "Remaining will be picked up in future runs.",
            store_key, unreplied_total, max_replies,
        )
        unreplied = unreplied[:max_replies]

    # --- Star-rating threshold --- #
    # Reviews below min_star_autoreply are held for manual handling instead of
    # receiving an AI-generated reply.  Default 1 = reply to everything.
    min_star: int = cfg.effective_defaults(store).get("min_star_autoreply", 1)
    manual: list[dict[str, Any]] = []
    if min_star > 1:
        auto_reply: list[dict[str, Any]] = []
        for r in unreplied:
            if _star_to_int(r.get("starRating", "THREE")) < min_star:
                manual.append(r)
            else:
                auto_reply.append(r)
        if manual:
            logger.info(
                "[%s] %d review(s) held for manual reply (below min_star_autoreply=%d): %s",
                store_key, len(manual), min_star,
                [
                    f"{r.get('reviewer', {}).get('displayName', '?')} "
                    f"({r.get('starRating', '?')}★)"
                    for r in manual
                ],
            )
        unreplied = auto_reply

    # Always refresh the held-review snapshot in live mode.  Calling with an
    # empty list when min_star==1 (or when no reviews are below threshold)
    # clears any stale snapshot left over from a prior config where min_star>1.
    # Without this, `meo-export held-reviews` would keep showing old entries
    # even after the operator changed the config back to min_star_autoreply: 1.
    if not dry_run:
        held_snapshots = [
            {
                "review_id": _extract_review_id(r),
                "reviewer": r.get("reviewer", {}).get("displayName", ""),
                "stars": r.get("starRating", ""),
                "comment": r.get("comment", ""),
                "review_date": _parse_review_date(r),
            }
            for r in manual
        ]
        record_held_reviews(store_key, held_snapshots)

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
        "manual": len(manual),                        # held for manual reply (below star threshold)
        "errors": errors,
    }


_STAR_VALUES: dict[str, int] = {
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5,
}


def _star_to_int(rating: str) -> int:
    """Convert a GBP star-rating string to an integer (1–5). Unknown → 3."""
    return _STAR_VALUES.get(rating.upper(), 3)


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


def _parse_review_date(review: dict[str, Any]) -> str:
    """Return the review creation date as YYYY-MM-DD, or '' if absent or malformed.

    The GBP API returns createTime in RFC 3339 format (e.g. "2024-01-15T10:00:00.000Z").
    We extract the date part only — callers use this to populate the held-review snapshot
    so operators can see at a glance how old each held review is when they export to CSV.
    """
    ts = review.get("createTime", "")
    if not ts:
        return ""
    try:
        return ts.split("T")[0]
    except (IndexError, AttributeError):
        return ""


def _review_age_days(review: dict[str, Any]) -> float | None:
    """Return the age of a review in fractional days, or None if undetermined.

    Parses the GBP API's RFC 3339 createTime field.  Returns None for reviews
    with a missing or unparseable timestamp — callers treat None as "include
    this review" so we never silently drop reviews we can't date.
    """
    ts = review.get("createTime")
    if not ts:
        return None
    try:
        # GBP returns timestamps like "2024-01-15T10:00:00.000Z"
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (datetime.now(tz=timezone.utc) - dt).total_seconds() / 86400
    except (ValueError, TypeError):
        return None

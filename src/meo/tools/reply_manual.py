"""meo-reply-manual — post a reply to a specific held review directly from the CLI.

The held-review workflow:
  1. meo-review-alert / meo-export held-reviews  → see which reviews await a reply
  2. meo-held-reply-draft --store X              → get AI draft suggestions
  3. meo-reply-manual --store X --review ID --text "..."  → post a hand-written reply
     meo-reply-manual --store X --review ID --auto        → generate and post an AI reply

On success:
  - The reply is posted to GBP via reply_to_review().
  - The review is recorded in replied_reviews and removed from the held snapshot.
  - meo-export held-reviews will no longer list it.

Requirements:
  - GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN — GBP write access
  - ANTHROPIC_API_KEY (or OPENAI_API_KEY) — only when --auto is used

Usage:
    meo-reply-manual --store the_body_kyoto --review REVIEW_ID --text "ありがとうございます！"
    meo-reply-manual --store the_body_kyoto --review REVIEW_ID --auto
    meo-reply-manual --store the_body_kyoto --review REVIEW_ID --auto --dry-run
    python -m meo.tools.reply_manual --help
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from .. import config as cfg
from ..auth import get_credentials
from ..business_profile import BusinessProfileClient
from ..content import generate_reply
from ..state import (
    get_held_reviews,
    record_held_reviews,
    record_replied_review,
    record_reply_content,
)

logger = logging.getLogger(__name__)

_GBP_REPLY_TEXT_LIMIT = 4096  # GBP review reply character limit


def _find_held_review(store_key: str, review_id: str) -> dict[str, Any] | None:
    """Return the held-review snapshot entry for review_id, or None if not found."""
    for r in get_held_reviews(store_key):
        if r.get("review_id") == review_id:
            return r
    return None


def _remove_from_held(store_key: str, review_id: str) -> None:
    """Remove review_id from the held-review snapshot and persist the change."""
    remaining = [
        r for r in get_held_reviews(store_key) if r.get("review_id") != review_id
    ]
    record_held_reviews(store_key, remaining)


def _held_to_gbp_review(held: dict[str, Any]) -> dict[str, Any]:
    """Convert a held-review snapshot entry to a GBP-format review dict.

    generate_reply() expects the same dict shape as list_reviews() returns.
    We reconstruct it from the state snapshot so --auto works without an
    extra GBP API call.
    """
    return {
        "reviewer": {"displayName": held.get("reviewer", "")},
        "starRating": held.get("stars", "FIVE"),
        "comment": held.get("comment", ""),
    }


def run_reply_manual(
    store: dict[str, Any],
    review_id: str,
    reply_text: str,
    gbp: BusinessProfileClient,
    *,
    reviewer: str = "",
    stars: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Post a manually-supplied or AI-generated reply to a specific review.

    Args:
        store:       Store dict from config.store_list().
        review_id:   Bare review ID (from meo-export held-reviews output).
        reply_text:  Reply text to post (caller supplies; see main() for --auto flow).
        gbp:         Authenticated BusinessProfileClient.
        reviewer:    Reviewer display name — used for history recording only.
        stars:       Star rating string (ONE/TWO/…/FIVE) — for history recording only.
        dry_run:     If True, log what would be posted without making API writes.

    Returns:
        Result dict: {store_key, review_id, status, reply_text}.
        status is one of: "replied", "dry_run".

    Raises:
        ValueError: when location_id is not yet configured for the store.
    """
    store_key = store["key"]
    location_id = str(store.get("location_id") or "")

    if not location_id or "TODO" in location_id:
        raise ValueError(
            f"location_id is not configured for store '{store_key}'. "
            "Fill in config/stores.yaml before posting replies."
        )

    if len(reply_text) > _GBP_REPLY_TEXT_LIMIT:
        logger.warning(
            "[%s] Reply text is %d chars (GBP limit: %d). The API may reject the reply.",
            store_key, len(reply_text), _GBP_REPLY_TEXT_LIMIT,
        )

    if dry_run:
        logger.info(
            "[%s] DRY RUN — would reply to review %s:\n%s",
            store_key, review_id, reply_text,
        )
        return {
            "store_key": store_key,
            "review_id": review_id,
            "status": "dry_run",
            "reply_text": reply_text,
        }

    gbp.reply_to_review(location_id, review_id, reply_text)
    record_replied_review(store_key, review_id)
    record_reply_content(store_key, review_id, reviewer, stars, reply_text)
    _remove_from_held(store_key, review_id)

    logger.info(
        "[%s] Reply posted to review %s. Removed from held queue.", store_key, review_id
    )
    return {
        "store_key": store_key,
        "review_id": review_id,
        "status": "replied",
        "reply_text": reply_text,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Post a reply to a specific held review.\n\n"
            "The held-review workflow:\n"
            "  1. meo-review-alert / meo-export held-reviews  → see which reviews await a reply\n"
            "  2. meo-held-reply-draft --store X              → get AI draft suggestions\n"
            "  3. meo-reply-manual ... --text '...'           → post a hand-written reply\n"
            "     meo-reply-manual ... --auto                 → generate and post an AI reply"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--store",
        required=True,
        metavar="STORE_KEY",
        help=(
            "Store to reply from. "
            "Keys: the_body_osaka_shinsaibashi, the_body_kyoto, mybear_studio_kyoto"
        ),
    )
    parser.add_argument(
        "--review",
        required=True,
        metavar="REVIEW_ID",
        help=(
            "Bare review ID to reply to (shown in 'meo-export held-reviews' output). "
            "Example: AbCdEfGhIjKlMnOpQrSt"
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--text",
        metavar="TEXT",
        help="Reply text to post (supply the full reply body directly).",
    )
    mode.add_argument(
        "--auto",
        action="store_true",
        help=(
            "Generate a reply via AI using the review details from the held-review snapshot. "
            "The review must appear in 'meo-export held-reviews'."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be posted without making any API writes.",
    )
    args = parser.parse_args()

    # --- Validate store key ---
    stores = cfg.store_list()
    store_map = {s["key"]: s for s in stores}
    if args.store not in store_map:
        print(
            f"Unknown store key: {args.store!r}. "
            f"Valid keys: {sorted(store_map)}",
            file=sys.stderr,
        )
        sys.exit(1)
    store = store_map[args.store]

    # --- Resolve reply text and review metadata ---
    reviewer = ""
    stars = ""

    if args.auto:
        held = _find_held_review(args.store, args.review)
        if held is None:
            print(
                f"Review {args.review!r} not found in the held-review snapshot for store "
                f"{args.store!r}.\n"
                "Cannot generate an AI reply without the review details.\n"
                "Check the review ID from 'meo-export held-reviews' or 'meo-review-alert'.",
                file=sys.stderr,
            )
            sys.exit(1)

        reviewer = held.get("reviewer", "")
        stars = held.get("stars", "")
        review_dict = _held_to_gbp_review(held)

        print(f"Generating AI reply for review {args.review} ({stars})...")
        try:
            reply_text = generate_reply(review_dict, store)
        except Exception as exc:
            print(f"AI reply generation failed: {exc}", file=sys.stderr)
            sys.exit(1)

        print(f"Generated reply ({len(reply_text)} chars):")
        print(reply_text)
        print()
    else:
        reply_text = args.text  # always set when --auto is absent (argparse enforces required group)
        held = _find_held_review(args.store, args.review)
        if held is not None:
            reviewer = held.get("reviewer", "")
            stars = held.get("stars", "")
        else:
            logger.warning(
                "[%s] Review %r not found in held-review snapshot. "
                "Proceeding with --text; history will omit reviewer/stars.",
                args.store, args.review,
            )

    # --- Authenticate ---
    try:
        creds = get_credentials()
    except Exception as exc:
        print(f"Authentication failed: {exc}", file=sys.stderr)
        sys.exit(1)

    gbp = BusinessProfileClient(creds)

    # --- Post reply ---
    try:
        result = run_reply_manual(
            store,
            args.review,
            reply_text,
            gbp,
            reviewer=reviewer,
            stars=stars,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        sys.exit(1)

    prefix = "[DRY RUN] " if result["status"] == "dry_run" else ""
    print(
        f"{prefix}Reply posted for review {args.review} on "
        f"{store['name']} ({args.store})."
    )


if __name__ == "__main__":  # pragma: no cover
    main()

"""meo-dismiss — permanently dismiss held reviews from the manual-reply queue.

When a review is dismissed it is:
  1. Removed from the current held-review snapshot in state.json immediately,
     so ``meo-export held-reviews`` stops showing it right away.
  2. Added to the persistent ``dismissed_reviews`` set, so the daily runner
     skips it even if it keeps appearing in the GBP API without an owner reply
     (e.g. spam reviews, or reviews already replied to outside this tool).

Use this for reviews you have handled outside the tool, decided not to reply
to, or want to permanently ignore (spam, test reviews, etc.).

Usage:
    meo-dismiss --list [--store STORE_KEY]
        List all currently dismissed review IDs (all stores, or one).

    meo-dismiss --review-id REV_ID --store STORE_KEY
        Permanently dismiss one review.

    meo-dismiss --all --store STORE_KEY
        Dismiss ALL currently held reviews for a store at once.

    meo-dismiss --undismiss --review-id REV_ID --store STORE_KEY
        Undo a dismiss — the review re-enters the held queue on the next run
        if it is still below min_star_autoreply.

    python -m meo.tools.dismiss --help
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from .. import config as cfg
from ..state import (
    dismiss_held_review,
    get_dismissed_reviews,
    get_held_reviews,
    undismiss_held_review,
)


# ---------------------------------------------------------------------------
# Business logic (pure, no I/O — testable without argparse)
# ---------------------------------------------------------------------------

def run_dismiss(store_key: str, review_id: str) -> dict[str, Any]:
    """Permanently dismiss one review for store_key.

    Returns:
        {"store_key": str, "review_id": str, "already_dismissed": bool}
    """
    already = review_id in get_dismissed_reviews(store_key)
    dismiss_held_review(store_key, review_id)
    return {"store_key": store_key, "review_id": review_id, "already_dismissed": already}


def run_dismiss_all(store_key: str) -> dict[str, Any]:
    """Dismiss ALL currently held reviews for store_key.

    Returns:
        {"store_key": str, "dismissed": list[str]}
    """
    held = get_held_reviews(store_key)
    review_ids = [h["review_id"] for h in held if h.get("review_id")]
    for rid in review_ids:
        dismiss_held_review(store_key, rid)
    return {"store_key": store_key, "dismissed": review_ids}


def run_undismiss(store_key: str, review_id: str) -> dict[str, Any]:
    """Undo a dismiss for one review.

    Returns:
        {"store_key": str, "review_id": str, "was_dismissed": bool}
    """
    found = undismiss_held_review(store_key, review_id)
    return {"store_key": store_key, "review_id": review_id, "was_dismissed": found}


def run_list(stores: list[dict[str, Any]], store_key_filter: str | None = None) -> list[dict[str, Any]]:
    """List all dismissed review IDs, optionally filtered to one store.

    Returns:
        List of {"store_key": str, "store_name": str, "dismissed_ids": list[str]}
    """
    results: list[dict[str, Any]] = []
    for s in stores:
        if store_key_filter and s["key"] != store_key_filter:
            continue
        dismissed = get_dismissed_reviews(s["key"])
        results.append({
            "store_key": s["key"],
            "store_name": s["name"],
            "dismissed_ids": dismissed,
        })
    return results


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

_DIVIDER = "─" * 56


def _format_list(results: list[dict[str, Any]]) -> str:
    lines: list[str] = ["MEO Automation — 却下済みレビュー一覧"]
    total = sum(len(r["dismissed_ids"]) for r in results)
    if total == 0:
        lines.append("却下済みレビューはありません。")
        return "\n".join(lines)
    for r in results:
        ids = r["dismissed_ids"]
        if not ids:
            continue
        lines.append(f"\n{r['store_name']}  ({r['store_key']})")
        for rid in ids:
            lines.append(f"  • {rid}")
    lines.append(f"\n合計: {total}件")
    return "\n".join(lines)


def _format_dismiss(result: dict[str, Any]) -> str:
    rid = result["review_id"]
    store = result["store_key"]
    if result["already_dismissed"]:
        return f"✓ {rid} はすでに却下済みです ({store})"
    return f"✓ {rid} を却下しました ({store})"


def _format_dismiss_all(result: dict[str, Any]) -> str:
    store = result["store_key"]
    dismissed = result["dismissed"]
    if not dismissed:
        return f"保留中のレビューはありません ({store})"
    lines = [f"✓ {len(dismissed)}件を却下しました ({store}):"]
    for rid in dismissed:
        lines.append(f"  • {rid}")
    return "\n".join(lines)


def _format_undismiss(result: dict[str, Any]) -> str:
    rid = result["review_id"]
    store = result["store_key"]
    if result["was_dismissed"]:
        return f"✓ {rid} の却下を解除しました ({store}) — 次回の日次実行で保留キューに再表示されます"
    return f"⚠ {rid} は却下リストに見つかりませんでした ({store})"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="meo-dismiss",
        description=(
            "Permanently dismiss held reviews so the runner never queues them again.\n"
            "Reads/writes state.json only — no Google credentials needed."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  meo-dismiss --list                                   # all stores\n"
            "  meo-dismiss --list --store the_body_kyoto            # one store\n"
            "  meo-dismiss --review-id rev001 --store the_body_kyoto\n"
            "  meo-dismiss --all --store mybear_studio_kyoto        # dismiss all held\n"
            "  meo-dismiss --undismiss --review-id rev001 --store the_body_kyoto\n"
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_mode",
        help="List all dismissed review IDs (default when no other action flag given).",
    )
    parser.add_argument(
        "--review-id",
        metavar="REV_ID",
        help="Review ID to dismiss or undismiss.",
    )
    parser.add_argument(
        "--store",
        metavar="STORE_KEY",
        help=(
            "Store key to operate on. Required for --review-id and --all. "
            "Optional filter for --list."
        ),
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_held",
        help="Dismiss ALL currently held reviews for --store.",
    )
    parser.add_argument(
        "--undismiss",
        action="store_true",
        help="Undo a dismiss instead of creating one (requires --review-id and --store).",
    )
    args = parser.parse_args()

    stores = cfg.store_list()
    known_keys = {s["key"] for s in stores}

    # Validate --store when provided
    if args.store and args.store not in known_keys:
        print(
            f"Unknown store key: '{args.store}'. "
            f"Valid keys: {', '.join(sorted(known_keys))}",
            file=sys.stderr,
        )
        sys.exit(1)

    # --- --undismiss ---
    if args.undismiss:
        if not args.review_id or not args.store:
            print("--undismiss requires both --review-id and --store.", file=sys.stderr)
            sys.exit(1)
        result = run_undismiss(args.store, args.review_id)
        print(_format_undismiss(result))
        sys.exit(0)

    # --- --all ---
    if args.all_held:
        if not args.store:
            print("--all requires --store.", file=sys.stderr)
            sys.exit(1)
        result = run_dismiss_all(args.store)
        print(_format_dismiss_all(result))
        sys.exit(0)

    # --- --review-id (single dismiss) ---
    if args.review_id:
        if not args.store:
            print("--review-id requires --store.", file=sys.stderr)
            sys.exit(1)
        result = run_dismiss(args.store, args.review_id)
        print(_format_dismiss(result))
        sys.exit(0)

    # --- --list (default) ---
    results = run_list(stores, store_key_filter=args.store)
    print(_format_list(results))
    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    main()

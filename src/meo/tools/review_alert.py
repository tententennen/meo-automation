"""meo-review-alert — Slack alert for reviews held for manual reply.

Reads the held-review snapshot from logs/state.json (written by the daily runner)
and sends an urgent Slack notification when any store has reviews waiting for
manual attention.

Designed to run as a post-step in the daily CI job so the owner is alerted
immediately when a low-star review needs a personal response, rather than
discovering it later in the weekly digest.

Usage:
    meo-review-alert               # send to Slack when reviews pending, exit 1
    meo-review-alert --dry-run     # print to stdout only, skip Slack
    meo-review-alert --store the_body_kyoto  # check one store
    python -m meo.tools.review_alert
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

import requests

from .. import config as cfg
from ..state import get_held_reviews

logger = logging.getLogger(__name__)

_STAR_SYMBOLS: dict[str, str] = {
    "FIVE":  "★★★★★",
    "FOUR":  "★★★★☆",
    "THREE": "★★★☆☆",
    "TWO":   "★★☆☆☆",
    "ONE":   "★☆☆☆☆",
}

# Number of comment characters to show per review in the alert.
_COMMENT_PREVIEW_LEN = 80


def _star_symbol(rating: str) -> str:
    """Return a visual star-symbol string for the given GBP rating word.

    Falls back to the raw rating string for any unrecognised value so the
    alert is never silently incomplete.
    """
    return _STAR_SYMBOLS.get(rating.upper() if rating else "", rating or "？")


def run_review_alert(store_keys: list[str] | None = None) -> dict[str, Any]:
    """Check all (or selected) stores for reviews held for manual reply.

    Reads the snapshot written by the previous daily run — no Google API calls.

    Args:
        store_keys: Optional list of store keys to check; defaults to all stores.

    Returns:
        {
            "stores_with_held": [
                {"store_key": str, "store_name": str, "reviews": list[dict]},
                ...
            ],
            "total_held": int,
        }
    """
    stores = cfg.store_list()
    if store_keys:
        stores = [s for s in stores if s["key"] in store_keys]

    stores_with_held: list[dict[str, Any]] = []
    total = 0

    for store in stores:
        key = store["key"]
        held = get_held_reviews(key)
        if held:
            stores_with_held.append(
                {
                    "store_key": key,
                    "store_name": store["name"],
                    "reviews": held,
                }
            )
            total += len(held)

    return {
        "stores_with_held": stores_with_held,
        "total_held": total,
    }


def _format_alert(result: dict[str, Any]) -> str:
    """Build the Slack alert text from a run_review_alert() result."""
    total = result["total_held"]
    blocks = result["stores_with_held"]

    divider = "─" * 40
    lines: list[str] = [
        f"⚠️ *MEO レビューアラート* — {total}件のレビューが手動返信待ちです",
        "",
    ]

    for block in blocks:
        name = block["store_name"]
        key = block["store_key"]
        reviews = block["reviews"]

        lines.append(divider)
        lines.append(f"*{name}* ({key}) — {len(reviews)}件")
        lines.append("")

        for r in reviews:
            star = _star_symbol(r.get("stars", ""))
            reviewer = r.get("reviewer") or "（匿名）"
            date_str = r.get("review_date") or r.get("date") or ""
            comment = r.get("comment", "")

            date_part = f"  {date_str}" if date_str else ""
            lines.append(f"  {star}  *{reviewer}*{date_part}")

            if comment:
                preview = (
                    comment[:_COMMENT_PREVIEW_LEN] + "…"
                    if len(comment) > _COMMENT_PREVIEW_LEN
                    else comment
                )
                lines.append(f"  「{preview}」")

        lines.append("")

    lines.append(divider)
    lines.append("`meo-export held-reviews` で詳細を確認し、手動で返信してください。")
    return "\n".join(lines)


def _send_alert(text: str) -> bool:
    """Send the alert to the Slack webhook.

    Returns True on success, False on any error (non-fatal — the caller
    already printed the alert to stdout).
    """
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_URL not set — review alert not sent to Slack.")
        return False
    try:
        resp = requests.post(webhook_url, json={"text": text}, timeout=10)
        resp.raise_for_status()
        logger.debug("Review alert sent to Slack.")
        return True
    except Exception as exc:
        logger.warning("Review alert Slack send failed (non-fatal): %s", exc)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Alert on reviews held for manual reply.\n"
            "Exits 0 when no reviews are pending; exits 1 when held reviews exist\n"
            "so CI can detect the condition and take further action."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print alert to stdout only — skip the Slack send.",
    )
    parser.add_argument(
        "--store",
        metavar="STORE_KEY",
        nargs="+",
        help=(
            "Check only these store key(s). Defaults to all stores.\n"
            "Keys: the_body_osaka_shinsaibashi, the_body_kyoto, mybear_studio_kyoto"
        ),
    )
    args = parser.parse_args()

    if args.store:
        known = {s["key"] for s in cfg.store_list()}
        unknown = [k for k in args.store if k not in known]
        if unknown:
            print(
                f"Unknown store key(s): {unknown}. Valid keys: {sorted(known)}",
                file=sys.stderr,
            )
            sys.exit(1)

    result = run_review_alert(args.store)
    total = result["total_held"]

    if total == 0:
        print("No held reviews — nothing to alert.", file=sys.stderr)
        sys.exit(0)

    text = _format_alert(result)
    print(text)

    if not args.dry_run:
        _send_alert(text)

    sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()

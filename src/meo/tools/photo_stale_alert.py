"""meo-photo-stale-alert — Slack alert when Drive photo variety is critically low.

Reads recently-used Drive image IDs from state.json and alerts when any store's
photo rotation is showing very low variety — a sign that the Drive folder has
too few images and posts are cycling through the same photos repeatedly.

The check is entirely offline (no Google credentials required).  It uses the
last ``--min-samples`` (default 5) image IDs recorded by the daily runner and
counts unique IDs.  When the unique count is below ``--min-variety`` (default 3),
the owner is prompted to upload more photos to the store's Drive folder.

A store whose ``drive_folder_id`` is still a placeholder (TODO) is skipped silently
because photo posting is not yet active for that store.

Exit codes:
  0 — all stores have sufficient photo variety (or not enough data yet)
  1 — one or more stores triggered the low-variety threshold (alert sent)

Usage:
    meo-photo-stale-alert                           # default thresholds
    meo-photo-stale-alert --min-variety 5           # alert when < 5 unique images
    meo-photo-stale-alert --min-samples 3           # alert after 3 posts (less data)
    meo-photo-stale-alert --dry-run                 # print without sending to Slack
    meo-photo-stale-alert --store the_body_kyoto    # check one store only
    python -m meo.tools.photo_stale_alert
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
from ..state import get_recent_images

logger = logging.getLogger(__name__)

_DEFAULT_MIN_SAMPLES = 5
_DEFAULT_MIN_VARIETY = 3


def compute_variety(
    stores: list[dict[str, Any]],
    min_samples: int = _DEFAULT_MIN_SAMPLES,
) -> list[dict[str, Any]]:
    """Return one dict per store that has a Drive folder configured and enough data.

    Stores with unconfigured folders or too few samples are excluded from the
    result so the caller does not have to filter them.

    Returned keys:
      store_key, store_name, folder_id, recent_count (int), unique_count (int).
    """
    result = []
    for store in stores:
        key = store["key"]
        folder_id: str = store.get("drive_folder_id", "")
        if not folder_id or "TODO" in folder_id:
            logger.debug("[%s] drive_folder_id not configured — skipped.", key)
            continue

        recent = get_recent_images(key)
        if len(recent) < min_samples:
            logger.debug(
                "[%s] Only %d recent image(s) recorded (min_samples=%d) — skipped.",
                key, len(recent), min_samples,
            )
            continue

        result.append(
            {
                "store_key": key,
                "store_name": store["name"],
                "folder_id": folder_id,
                "recent_count": len(recent),
                "unique_count": len(set(recent)),
            }
        )
    return result


def run_photo_stale_alert(
    stores: list[dict[str, Any]],
    min_samples: int = _DEFAULT_MIN_SAMPLES,
    min_variety: int = _DEFAULT_MIN_VARIETY,
) -> list[dict[str, Any]]:
    """Return alert dicts for stores whose photo variety is below min_variety.

    Args:
        stores:      Store dicts from cfg.store_list().
        min_samples: Minimum number of image history entries needed before
                     checking (skipped when not enough data).
        min_variety: Alert when unique image count is strictly below this value.

    Returns:
        List of per-store dicts (same shape as compute_variety) for stores that
        triggered the alert.
    """
    variety = compute_variety(stores, min_samples=min_samples)
    return [row for row in variety if row["unique_count"] < min_variety]


def _format_alert(
    alerts: list[dict[str, Any]],
    min_variety: int,
) -> str:
    """Build the Slack alert text for photo-variety failures."""
    n = len(alerts)
    divider = "─" * 40
    lines: list[str] = [
        f"📸 *MEO 写真アラート* — {n}店舗でDriveフォルダの写真種類が少なすぎます",
        "",
    ]

    for row in alerts:
        name = row["store_name"]
        key = row["store_key"]
        unique = row["unique_count"]
        total = row["recent_count"]
        folder_id = row["folder_id"]

        lines.append(divider)
        lines.append(f"*{name}* ({key})")
        lines.append(
            f"  直近{total}投稿のうち使用された画像種類: *{unique}種* "
            f"（必要最小: {min_variety}種）"
        )
        lines.append(f"  Driveフォルダ: `{folder_id}`")
        lines.append("")

    lines.append(divider)
    lines.append(
        "写真の繰り返し投稿を避けるため、各店舗のDriveフォルダに画像を追加してください。"
    )
    lines.append("`meo-photo-audit --live` で現在の在庫状況を確認できます。")
    return "\n".join(lines)


def _send_alert(text: str) -> bool:
    """POST the alert to SLACK_WEBHOOK_URL.  Returns True on success."""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_URL not set — photo-stale alert not sent to Slack.")
        return False
    try:
        resp = requests.post(webhook_url, json={"text": text}, timeout=10)
        resp.raise_for_status()
        logger.debug("Photo-stale alert sent to Slack.")
        return True
    except Exception as exc:
        logger.warning("Photo-stale alert Slack send failed (non-fatal): %s", exc)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Alert when a store's Drive photo variety is critically low.\n"
            "Exits 0 when all stores have sufficient variety; exits 1 when any\n"
            "store triggers so CI can surface the condition automatically."
        )
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=_DEFAULT_MIN_SAMPLES,
        metavar="N",
        help=(
            f"Minimum number of recent-image history entries required before "
            f"checking a store (default: {_DEFAULT_MIN_SAMPLES}).  Stores with "
            f"fewer entries are skipped — not enough data yet."
        ),
    )
    parser.add_argument(
        "--min-variety",
        type=int,
        default=_DEFAULT_MIN_VARIETY,
        metavar="N",
        help=(
            f"Alert when the number of unique images in the recent history is "
            f"strictly below this value (default: {_DEFAULT_MIN_VARIETY})."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the alert to stdout only — skip the Slack send.",
    )
    parser.add_argument(
        "--store",
        metavar="STORE_KEY",
        nargs="+",
        help=(
            "Check only these store key(s).  Defaults to all stores.\n"
            "Keys: the_body_osaka_shinsaibashi, the_body_kyoto, mybear_studio_kyoto"
        ),
    )
    args = parser.parse_args()

    if args.min_samples < 1:
        print("--min-samples must be >= 1", file=sys.stderr)
        sys.exit(1)
    if args.min_variety < 1:
        print("--min-variety must be >= 1", file=sys.stderr)
        sys.exit(1)

    stores = cfg.store_list()
    if args.store:
        known = {s["key"] for s in stores}
        unknown = [k for k in args.store if k not in known]
        if unknown:
            print(
                f"Unknown store key(s): {unknown}. Valid keys: {sorted(known)}",
                file=sys.stderr,
            )
            sys.exit(1)
        stores = [s for s in stores if s["key"] in args.store]

    alerts = run_photo_stale_alert(
        stores,
        min_samples=args.min_samples,
        min_variety=args.min_variety,
    )

    if not alerts:
        print("Photo variety OK — nothing to alert.", file=sys.stderr)
        sys.exit(0)

    text = _format_alert(alerts, min_variety=args.min_variety)
    print(text)

    if not args.dry_run:
        _send_alert(text)

    sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()

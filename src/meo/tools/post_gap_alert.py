"""meo-post-gap-alert — Slack alert when a store hasn't posted in too long.

Reads the last-post date from state.json for each store.  When any store has
gone >= --max-gap-days since its last 最新情報 post (or has never posted and
--include-never-posted is set), a Slack alert is formatted and sent.

Exit codes:
  0 — all stores posted within the gap window
  1 — one or more stores exceeded the gap (alert sent)

Usage:
    meo-post-gap-alert                          # default gap (3 × cadence_days)
    meo-post-gap-alert --max-gap-days 5         # alert after 5-day gap
    meo-post-gap-alert --include-never-posted   # also alert for stores never posted
    meo-post-gap-alert --dry-run                # print without sending to Slack
    meo-post-gap-alert --store the_body_kyoto   # check one store only
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

from .. import config as cfg
from ..state import get_last_post_date

logger = logging.getLogger(__name__)

_JST = ZoneInfo("Asia/Tokyo")
# Multiplier over post_cadence_days used when --max-gap-days is not supplied.
_DEFAULT_GAP_MULTIPLIER = 3


def _today_jst() -> date:
    return datetime.now(tz=_JST).date()


def _default_max_gap() -> int:
    """Return cadence_days * 3 as the default gap threshold."""
    try:
        cadence = int(cfg.content().get("defaults", {}).get("post_cadence_days", 1))
    except Exception:
        cadence = 1
    return max(1, cadence) * _DEFAULT_GAP_MULTIPLIER


def compute_gaps(
    stores: list[dict[str, Any]],
    today: date | None = None,
    include_never_posted: bool = False,
) -> list[dict[str, Any]]:
    """Return one dict per store with gap metadata.

    Returned keys:
      store_key, store_name, last_post_date (str | None), days_since (int | None).
    ``days_since`` is None when the store has never posted.
    """
    if today is None:
        today = _today_jst()
    result = []
    for store in stores:
        key = store["key"]
        raw = get_last_post_date(key)
        days_since: int | None = None
        if raw:
            try:
                last = date.fromisoformat(raw)
                days_since = (today - last).days
            except ValueError:
                logger.warning("Invalid last_post date '%s' for %s — treating as never posted.", raw, key)
                raw = None
        if raw is None and not include_never_posted:
            continue
        result.append({
            "store_key": key,
            "store_name": store["name"],
            "last_post_date": raw,
            "days_since": days_since,
        })
    return result


def run_post_gap_alert(
    stores: list[dict[str, Any]],
    max_gap_days: int | None = None,
    today: date | None = None,
    include_never_posted: bool = False,
) -> list[dict[str, Any]]:
    """Return alert dicts for stores that exceeded ``max_gap_days`` since last post.

    Each returned dict has keys: store_key, store_name, last_post_date, days_since.
    """
    if max_gap_days is None:
        max_gap_days = _default_max_gap()
    gaps = compute_gaps(stores, today=today, include_never_posted=include_never_posted)
    alerts = []
    for g in gaps:
        if g["days_since"] is None:
            # never posted — include only when include_never_posted=True (already filtered)
            alerts.append(g)
        elif g["days_since"] >= max_gap_days:
            alerts.append(g)
    return alerts


def _format_alert(
    alerts: list[dict[str, Any]],
    max_gap_days: int,
    now: str | None = None,
) -> str:
    """Format the Slack alert message."""
    if now is None:
        now = datetime.now(tz=_JST).strftime("%Y-%m-%d %H:%M JST")
    count = len(alerts)
    lines = [
        f"⚠️ MEO 投稿ギャップアラート — {count}店舗で投稿が{max_gap_days}日以上ありません",
        "",
        f"生成日時: {now}",
        "",
    ]
    sep = "─" * 48
    for a in alerts:
        lines.append(sep)
        lines.append(f"{a['store_name']}  ({a['store_key']})")
        if a["last_post_date"] is None:
            lines.append("  最終投稿日: なし（未投稿）")
        else:
            lines.append(f"  最終投稿日: {a['last_post_date']}")
            lines.append(f"  経過日数:   {a['days_since']}日")
    lines.append(sep)
    lines.append("")
    lines.append(f"投稿が{max_gap_days}日以上滞っています。`meo-run` を確認してください。")
    return "\n".join(lines)


def _send_alert(message: str) -> bool:
    """POST message to SLACK_WEBHOOK_URL; returns True on success."""
    url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not url:
        logger.debug("SLACK_WEBHOOK_URL not set — skipping Slack post-gap alert.")
        return False
    try:
        resp = requests.post(url, json={"text": message}, timeout=10)
        resp.raise_for_status()
        return True
    except requests.HTTPError as exc:
        logger.warning("Slack post-gap-alert HTTP error: %s", exc)
    except Exception as exc:
        logger.warning("Slack post-gap-alert send failed: %s", exc)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Alert via Slack when a store hasn't posted in too long.",
    )
    parser.add_argument(
        "--max-gap-days",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Days without a post before alerting "
            f"(default: {_DEFAULT_GAP_MULTIPLIER}× post_cadence_days from content.yaml)."
        ),
    )
    parser.add_argument(
        "--include-never-posted",
        action="store_true",
        help="Also alert for stores that have never posted (no state.json entry).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the alert to stdout but do not send to Slack.",
    )
    parser.add_argument(
        "--store",
        nargs="+",
        metavar="STORE_KEY",
        help="Check only the given store key(s).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    max_gap_days: int = args.max_gap_days if args.max_gap_days is not None else _default_max_gap()
    if max_gap_days < 1:
        print("--max-gap-days must be >= 1", file=sys.stderr)
        sys.exit(1)

    stores = cfg.store_list()
    if args.store:
        known = {s["key"] for s in stores}
        unknown = [k for k in args.store if k not in known]
        if unknown:
            print(
                f"Unknown store key(s): {unknown}. Valid: {sorted(known)}",
                file=sys.stderr,
            )
            sys.exit(1)
        stores = [s for s in stores if s["key"] in args.store]

    alerts = run_post_gap_alert(
        stores,
        max_gap_days=max_gap_days,
        include_never_posted=args.include_never_posted,
    )

    if not alerts:
        print("No post gaps detected.", file=sys.stderr)
        sys.exit(0)

    message = _format_alert(alerts, max_gap_days=max_gap_days)
    print(message)

    if not args.dry_run:
        _send_alert(message)

    sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()

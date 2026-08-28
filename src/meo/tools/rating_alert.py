"""meo-rating-alert — Slack alert when a store's reply star-rating declines.

Compares the mean star rating of replied reviews in the current window
(last N days) against the previous window (the N days before that).
Fires a Slack alert when any store drops by more than --min-drop stars
AND has at least --min-replies replies in the current window (to avoid
false alarms from thin data).

Reads reply_history from logs/state.json — no Google credentials needed.

Exit codes:
  0 — no significant rating declines detected
  1 — at least one store has a significant decline (alert sent/printed)

Usage:
    meo-rating-alert                            # all stores, 14-day windows
    meo-rating-alert --window-days 7            # 7-day windows
    meo-rating-alert --min-drop 1.0             # alert only on >=1.0 star drop
    meo-rating-alert --min-replies 5            # require >=5 replies to alert
    meo-rating-alert --dry-run                  # print without sending to Slack
    meo-rating-alert --store the_body_kyoto     # single store
    python -m meo.tools.rating_alert
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

import requests

from .. import config as cfg
from ..state import get_reply_history

logger = logging.getLogger(__name__)

_JST = ZoneInfo("Asia/Tokyo")

_DEFAULT_WINDOW_DAYS = 14
_DEFAULT_MIN_DROP = 0.5      # stars
_DEFAULT_MIN_REPLIES = 3     # minimum replies in current window to alert

_STAR_VALUES: dict[str, int] = {
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5,
}
_STAR_SYMBOLS: dict[str, str] = {
    "ONE": "★☆☆☆☆",
    "TWO": "★★☆☆☆",
    "THREE": "★★★☆☆",
    "FOUR": "★★★★☆",
    "FIVE": "★★★★★",
}
_STAR_ORDER = ["FIVE", "FOUR", "THREE", "TWO", "ONE"]


def _star_value(star_str: str) -> int:
    return _STAR_VALUES.get(star_str, 0)


def _avg_stars(entries: list[dict[str, Any]]) -> float | None:
    values = [_star_value(e.get("stars", "")) for e in entries if _star_value(e.get("stars", ""))]
    return round(sum(values) / len(values), 2) if values else None


def _window_entries(
    history: list[dict[str, Any]],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Return entries whose 'date' field falls within [start, end] (inclusive)."""
    result = []
    for e in history:
        raw = e.get("date", "")
        if not raw:
            continue
        try:
            d = date.fromisoformat(raw)
        except ValueError:
            continue
        if start <= d <= end:
            result.append(e)
    return result


def run_rating_alert(
    stores: list[dict[str, Any]],
    *,
    window_days: int = _DEFAULT_WINDOW_DAYS,
    min_drop: float = _DEFAULT_MIN_DROP,
    min_replies: int = _DEFAULT_MIN_REPLIES,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Compute rating-decline alerts for each store.

    Args:
        stores:      Store list from config.store_list().
        window_days: Size of each comparison window in days.
        min_drop:    Minimum average-star drop (current vs previous) to alert.
        min_replies: Minimum replies required in the current window to alert.
        today:       Reference date (default: today in JST).

    Returns:
        List of alert dicts for stores with significant declines.  Each dict:
            store_key, store_name,
            cur_avg, prev_avg, drop,
            cur_count, prev_count,
            cur_start, cur_end,   (ISO date strings)
            prev_start, prev_end, (ISO date strings)
            cur_distribution,     (Counter[str])
    """
    if today is None:
        today = datetime.now(tz=_JST).date()

    cur_end = today - timedelta(days=1)          # yesterday
    cur_start = cur_end - timedelta(days=window_days - 1)
    prev_end = cur_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=window_days - 1)

    alerts: list[dict[str, Any]] = []
    for store in stores:
        key = store["key"]
        history = get_reply_history(key)

        cur_entries = _window_entries(history, cur_start, cur_end)
        prev_entries = _window_entries(history, prev_start, prev_end)

        cur_avg = _avg_stars(cur_entries)
        prev_avg = _avg_stars(prev_entries)

        if cur_avg is None or prev_avg is None:
            continue
        drop = prev_avg - cur_avg
        if drop < min_drop:
            continue
        if len(cur_entries) < min_replies:
            continue

        alerts.append({
            "store_key": key,
            "store_name": store["name"],
            "cur_avg": cur_avg,
            "prev_avg": prev_avg,
            "drop": round(drop, 2),
            "cur_count": len(cur_entries),
            "prev_count": len(prev_entries),
            "cur_start": cur_start.isoformat(),
            "cur_end": cur_end.isoformat(),
            "prev_start": prev_start.isoformat(),
            "prev_end": prev_end.isoformat(),
            "cur_distribution": Counter(
                e.get("stars", "") for e in cur_entries if e.get("stars")
            ),
        })

    return alerts


def _format_alert(
    alerts: list[dict[str, Any]],
    *,
    window_days: int = _DEFAULT_WINDOW_DAYS,
    today_str: str | None = None,
) -> str:
    if today_str is None:
        today_str = datetime.now(tz=_JST).strftime("%Y-%m-%d %H:%M JST")

    count = len(alerts)
    lines = [
        f"⚠️  MEO 評価低下アラート — {count}店舗で直近{window_days}日間の星評価が低下しています",
        "",
        f"生成日時: {today_str}",
        "",
    ]
    sep = "─" * 50
    for a in alerts:
        lines.append(sep)
        lines.append(f"{a['store_name']}  ({a['store_key']})")
        cur_str = f"★{a['cur_avg']:.2f}" if a["cur_avg"] is not None else "—"
        prev_str = f"★{a['prev_avg']:.2f}" if a["prev_avg"] is not None else "—"
        lines.append(
            f"  直近{window_days}日: {cur_str} ({a['cur_count']}件)  "
            f"前期{window_days}日: {prev_str} ({a['prev_count']}件)  "
            f"→  ▼{a['drop']:.2f}"
        )
        lines.append(
            f"  期間: {a['cur_start']}〜{a['cur_end']}  "
            f"(前期: {a['prev_start']}〜{a['prev_end']})"
        )
        dist = a.get("cur_distribution", {})
        if dist:
            lines.append("  直近分布:")
            for rating in _STAR_ORDER:
                cnt = dist.get(rating, 0)
                if cnt:
                    lines.append(
                        f"    {_STAR_SYMBOLS.get(rating, rating)}  {cnt}件"
                    )
    lines.append(sep)
    lines.append("")
    lines.append(
        "低評価レビューへの手動対応をご検討ください。"
        " `meo-export reviews` で詳細を確認できます。"
    )
    return "\n".join(lines)


def _send_alert(message: str) -> bool:
    url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not url:
        logger.debug("SLACK_WEBHOOK_URL not set — skipping Slack rating alert.")
        return False
    try:
        resp = requests.post(url, json={"text": message}, timeout=10)
        resp.raise_for_status()
        return True
    except requests.HTTPError as exc:
        logger.warning("Slack rating-alert HTTP error: %s", exc)
    except Exception as exc:
        logger.warning("Slack rating-alert send failed: %s", exc)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Alert via Slack when a store's average reply star-rating declines "
            "significantly period-over-period. No Google credentials required."
        ),
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=_DEFAULT_WINDOW_DAYS,
        metavar="N",
        help=f"Size of each comparison window in days (default: {_DEFAULT_WINDOW_DAYS}).",
    )
    parser.add_argument(
        "--min-drop",
        type=float,
        default=_DEFAULT_MIN_DROP,
        metavar="STARS",
        help=(
            f"Minimum drop in average stars to trigger an alert "
            f"(default: {_DEFAULT_MIN_DROP})."
        ),
    )
    parser.add_argument(
        "--min-replies",
        type=int,
        default=_DEFAULT_MIN_REPLIES,
        metavar="N",
        help=(
            f"Minimum replies in the current window required to alert "
            f"(avoids false alarms from thin data; default: {_DEFAULT_MIN_REPLIES})."
        ),
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

    if args.window_days < 1:
        print("--window-days must be >= 1", file=sys.stderr)
        sys.exit(1)
    if args.min_drop <= 0:
        print("--min-drop must be > 0", file=sys.stderr)
        sys.exit(1)
    if args.min_replies < 1:
        print("--min-replies must be >= 1", file=sys.stderr)
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

    alerts = run_rating_alert(
        stores,
        window_days=args.window_days,
        min_drop=args.min_drop,
        min_replies=args.min_replies,
    )

    if not alerts:
        print("No significant rating declines detected.", file=sys.stderr)
        sys.exit(0)

    message = _format_alert(alerts, window_days=args.window_days)
    print(message)

    if not args.dry_run:
        _send_alert(message)

    sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()

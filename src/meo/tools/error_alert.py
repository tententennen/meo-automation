"""meo-error-alert — Slack alert when consecutive live-run failures are detected.

Reads the run-result streak from state.json (written by meo-run after each live
run). When any store has >= --threshold consecutive failures an alert is formatted
and sent to SLACK_WEBHOOK_URL.

Exit codes:
  0 — all stores within threshold (healthy or no data yet)
  1 — one or more stores have met or exceeded the failure threshold (alert sent)

Usage:
    meo-error-alert                          # default threshold (2)
    meo-error-alert --threshold 3            # alert after 3 consecutive failures
    meo-error-alert --dry-run                # print alert without sending to Slack
    meo-error-alert --store the_body_kyoto   # check one store only
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

from .. import config as cfg
from ..state import get_run_streak

logger = logging.getLogger(__name__)

_JST = ZoneInfo("Asia/Tokyo")
_DEFAULT_THRESHOLD = 2

_ERROR_TYPE_LABELS: dict[str, str] = {
    "post_error": "投稿エラー",
    "review_error": "レビュー返信エラー",
    "both_error": "投稿・返信エラー",
}


def run_error_alert(
    stores: list[dict[str, Any]],
    threshold: int = _DEFAULT_THRESHOLD,
) -> list[dict[str, Any]]:
    """Return alert dicts for stores at or above ``threshold`` consecutive failures.

    Each returned dict has keys: store_key, store_name, consecutive_failures,
    last_error_type, last_error_date.
    """
    alerts = []
    for store in stores:
        key = store["key"]
        streak = get_run_streak(key)
        if streak["consecutive_failures"] >= threshold:
            alerts.append({
                "store_key": key,
                "store_name": store["name"],
                "consecutive_failures": streak["consecutive_failures"],
                "last_error_type": streak["last_error_type"],
                "last_error_date": streak["last_error_date"],
            })
    return alerts


def _format_alert(alerts: list[dict[str, Any]], today: str | None = None) -> str:
    """Format the Slack alert message for the given list of store alerts."""
    if today is None:
        today = datetime.now(tz=_JST).strftime("%Y-%m-%d %H:%M JST")
    count = len(alerts)
    lines = [
        f"🚨 MEO 連続エラーアラート — {count}店舗でエラーが継続しています",
        "",
        f"生成日時: {today}",
        "",
    ]
    sep = "─" * 48
    for alert in alerts:
        lines.append(sep)
        lines.append(f"{alert['store_name']}  ({alert['store_key']})")
        lines.append(f"  連続エラー: {alert['consecutive_failures']}回")
        err_type = alert.get("last_error_type")
        label = _ERROR_TYPE_LABELS.get(err_type or "", err_type or "不明")
        lines.append(f"  エラー種別: {label}")
        err_date = alert.get("last_error_date") or "不明"
        lines.append(f"  最終エラー日: {err_date}")
    lines.append(sep)
    lines.append("")
    lines.append("`meo-run` の GitHub Actions ログを確認してください。")
    return "\n".join(lines)


def _send_alert(message: str) -> bool:
    """POST message to SLACK_WEBHOOK_URL; returns True on success."""
    url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not url:
        logger.debug("SLACK_WEBHOOK_URL not set — skipping Slack error alert.")
        return False
    try:
        resp = requests.post(url, json={"text": message}, timeout=10)
        resp.raise_for_status()
        return True
    except requests.HTTPError as exc:
        logger.warning("Slack error-alert HTTP error: %s", exc)
    except Exception as exc:
        logger.warning("Slack error-alert send failed: %s", exc)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Alert via Slack when consecutive live-run failures are detected.",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=_DEFAULT_THRESHOLD,
        metavar="N",
        help=f"Consecutive failures before alerting (default: {_DEFAULT_THRESHOLD}).",
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

    if args.threshold < 1:
        print("--threshold must be >= 1", file=sys.stderr)
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

    alerts = run_error_alert(stores, threshold=args.threshold)

    if not alerts:
        print("No consecutive run errors detected.", file=sys.stderr)
        sys.exit(0)

    message = _format_alert(alerts)
    print(message)

    if not args.dry_run:
        _send_alert(message)

    sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()

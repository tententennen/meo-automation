"""meo-monthly-digest — send a previous-month Slack summary of posts and replies.

Reads the content archive in logs/state.json (written by the daily runner)
and reports, per store: how many posts and review replies were made in the
previous complete calendar month in JST, with theme and full star-rating
breakdowns.

Usage:
    meo-monthly-digest               # build digest, send to Slack (if configured), print to stdout
    meo-monthly-digest --dry-run     # print to stdout only, skip Slack
    python -m meo.tools.monthly_digest
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
from ..state import get_post_history, get_reply_history

logger = logging.getLogger(__name__)

_JST = ZoneInfo("Asia/Tokyo")

_STAR_ORDER = ["FIVE", "FOUR", "THREE", "TWO", "ONE"]
_STAR_SYMBOLS = {
    "FIVE":  "★★★★★",
    "FOUR":  "★★★★☆",
    "THREE": "★★★☆☆",
    "TWO":   "★★☆☆☆",
    "ONE":   "★☆☆☆☆",
}

# Monthly digest shows more themes than the weekly digest (more data = richer view).
_TOP_THEMES = 5

_DIVIDER = "━" * 42

# Month name table for Japanese header.
_MONTH_JA = {
    1: "1月", 2: "2月", 3: "3月", 4: "4月",
    5: "5月", 6: "6月", 7: "7月", 8: "8月",
    9: "9月", 10: "10月", 11: "11月", 12: "12月",
}


def _month_range() -> tuple[date, date]:
    """Return (first, last) day of the previous full calendar month in JST.

    E.g. called on 2026-08-01 → (2026-07-01, 2026-07-31)
         called on 2026-08-15 → still (2026-07-01, 2026-07-31)
    """
    today = datetime.now(tz=_JST).date()
    first_of_this_month = today.replace(day=1)
    last_of_prev_month = first_of_this_month - timedelta(days=1)
    first_of_prev_month = last_of_prev_month.replace(day=1)
    return first_of_prev_month, last_of_prev_month


def _month_label(first: date) -> str:
    """Return a Japanese month label like '2026年7月'."""
    return f"{first.year}年{_MONTH_JA[first.month]}"


def _filter_by_date(entries: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    """Return only entries whose 'date' field falls within [start, end] inclusive."""
    result = []
    for entry in entries:
        raw = entry.get("date", "")
        try:
            d = date.fromisoformat(raw)
        except (ValueError, TypeError):
            continue
        if start <= d <= end:
            result.append(entry)
    return result


def _format_theme_line(posts: list[dict[str, Any]]) -> str:
    """Return a compact top-themes parenthetical like '(テーマA ×3, テーマB ×2)'.

    Returns an empty string when no themed posts exist.
    """
    if not posts:
        return ""
    counter: Counter[str] = Counter(p.get("theme", "") for p in posts if p.get("theme"))
    if not counter:
        return ""
    top = counter.most_common(_TOP_THEMES)
    return "  (" + ", ".join(f"{theme} ×{cnt}" for theme, cnt in top) + ")"


def _format_star_line(replies: list[dict[str, Any]]) -> str:
    """Return a full star-distribution line including all five ratings.

    Unlike the weekly digest, the monthly digest shows all five star levels —
    even zeros — so the owner can see at a glance that e.g. no 1-star reviews
    were replied to this month. Returns an empty string for empty input.

    Example: '  |  ★★★★★ 11  ★★★★☆ 4  ★★★☆☆ 2  ★★☆☆☆ 1  ★☆☆☆☆ 0'
    """
    if not replies:
        return ""
    counter: Counter[str] = Counter(r.get("stars", "") for r in replies)
    parts = [
        f"{_STAR_SYMBOLS[rating]} {counter.get(rating, 0)}"
        for rating in _STAR_ORDER
    ]
    return "  |  " + "  ".join(parts)


def _format_store_block(store: dict[str, Any], posts: list[dict[str, Any]], replies: list[dict[str, Any]]) -> list[str]:
    """Return Slack-formatted lines for a single store."""
    name = store["name"]
    key = store["key"]

    theme_str = _format_theme_line(posts)
    star_str = _format_star_line(replies)

    return [
        _DIVIDER,
        f"*{name}* ({key})",
        f"  \U0001f4dd 投稿: {len(posts)}件{theme_str}",
        f"  \U0001f4ac 返信: {len(replies)}件{star_str}",
    ]


def _format_digest(
    results: list[tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]],
    start: date,
    end: date,
) -> str:
    """Build the full Slack message for the monthly digest."""
    label = _month_label(start)
    lines: list[str] = [
        f"*MEO Automation — 月次サマリー ({label})*",
        "",
    ]

    total_posts = 0
    total_replies = 0
    for store, posts, replies in results:
        lines.extend(_format_store_block(store, posts, replies))
        total_posts += len(posts)
        total_replies += len(replies)

    lines.append(_DIVIDER)
    lines.append(f"合計: 投稿 {total_posts}件, 返信 {total_replies}件")
    return "\n".join(lines)


def _send_to_slack(text: str) -> None:
    """Post text to the Slack webhook. Silently no-ops when SLACK_WEBHOOK_URL is not set."""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return
    try:
        resp = requests.post(webhook_url, json={"text": text}, timeout=10)
        resp.raise_for_status()
        logger.debug("Monthly digest sent to Slack.")
    except Exception as exc:
        logger.warning("Monthly digest Slack send failed (non-fatal): %s", exc)


def run_monthly_digest(*, dry_run: bool = False) -> str:
    """Collect the previous calendar month's activity, format the digest, and (unless dry_run) send to Slack.

    Returns:
        The formatted digest text (always — useful for testing and stdout printing).
    """
    start, end = _month_range()
    stores = cfg.store_list()

    results: list[tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]] = []
    for store in stores:
        key = store["key"]
        posts = _filter_by_date(get_post_history(key), start, end)
        replies = _filter_by_date(get_reply_history(key), start, end)
        results.append((store, posts, replies))

    text = _format_digest(results, start, end)

    if not dry_run:
        _send_to_slack(text)

    return text


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send a previous-month MEO activity summary to Slack."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the digest to stdout only — skip Slack send.",
    )
    args = parser.parse_args()

    text = run_monthly_digest(dry_run=args.dry_run)
    print(text)


if __name__ == "__main__":  # pragma: no cover
    main()

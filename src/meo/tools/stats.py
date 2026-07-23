"""meo-stats — aggregate statistics across the full post/reply history.

Reads the content archive in logs/state.json (written by the daily runner)
and shows per-store totals, activity rates, theme frequencies, and star-rating
distributions at a glance.  Nothing is written; this command is fully read-only.

Usage:
    meo-stats                         # all stores
    meo-stats --store the_body_kyoto  # single store
    python -m meo.tools.stats
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from .. import config as cfg
from ..state import get_post_history, get_reply_history

_JST = ZoneInfo("Asia/Tokyo")

_STAR_ORDER = ["FIVE", "FOUR", "THREE", "TWO", "ONE"]
_STAR_DISPLAY = {
    "FIVE":  "★★★★★",
    "FOUR":  "★★★★☆",
    "THREE": "★★★☆☆",
    "TWO":   "★★☆☆☆",
    "ONE":   "★☆☆☆☆",
}
_BAR_WIDTH = 12  # max bar length (characters)
_TOP_THEMES = 5  # how many top themes to display


def _date_range(entries: list[dict[str, Any]]) -> tuple[str, str] | None:
    """Return (first_date, last_date) from a list of history entries, or None."""
    dates = [e["date"] for e in entries if e.get("date")]
    if not dates:
        return None
    return min(dates), max(dates)


def _posts_per_week(first: str, last: str, total: int) -> str:
    """Return a human-readable posts-per-week rate string."""
    try:
        d1 = date.fromisoformat(first)
        d2 = date.fromisoformat(last)
        days = max((d2 - d1).days, 1)
        weeks = days / 7
        rate = total / weeks
        return f"~{rate:.1f}/week"
    except ValueError:
        return ""


def _bar(count: int, total: int) -> str:
    """Return an ASCII bar proportional to count/total."""
    if total == 0:
        return ""
    filled = round(_BAR_WIDTH * count / total)
    return "█" * filled


def _format_store_section(store: dict[str, Any]) -> str:
    key = store["key"]
    name = store["name"]
    sep = "─" * 62

    lines = [sep, f"  {name}", f"  key: {key}", sep]

    # ── Posts ──────────────────────────────────────────────────────
    posts = get_post_history(key)
    lines.append(f"\n  最新情報 Posts  (up to 30 archived)")
    if not posts:
        lines.append("  (no posts archived yet)")
    else:
        dr = _date_range(posts)
        period_str = ""
        rate_str = ""
        if dr:
            period_str = f"{dr[0]} → {dr[1]}"
            try:
                d1 = date.fromisoformat(dr[0])
                d2 = date.fromisoformat(dr[1])
                days = max((d2 - d1).days, 1)
                period_str += f"  ({days} days)"
            except ValueError:
                pass
            rate_str = _posts_per_week(dr[0], dr[1], len(posts))

        lines.append(f"    Total archived: {len(posts)}")
        if period_str:
            lines.append(f"    Period:         {period_str}")
        if rate_str:
            lines.append(f"    Rate:           {rate_str}")

        theme_counter: Counter[str] = Counter(
            e.get("theme", "") for e in posts if e.get("theme")
        )
        if theme_counter:
            lines.append(f"    Top themes:")
            for theme, cnt in theme_counter.most_common(_TOP_THEMES):
                lines.append(f"      {theme:<36}  {cnt}×")

    # ── Replies ────────────────────────────────────────────────────
    replies = get_reply_history(key)
    lines.append(f"\n  Review Replies  (up to 50 archived)")
    if not replies:
        lines.append("  (no replies archived yet)")
    else:
        dr = _date_range(replies)
        period_str = ""
        if dr:
            period_str = f"{dr[0]} → {dr[1]}"

        lines.append(f"    Total archived: {len(replies)}")
        if period_str:
            lines.append(f"    Period:         {period_str}")

        star_counter: Counter[str] = Counter(e.get("stars", "") for e in replies)
        total_replies = len(replies)
        lines.append("    Star distribution:")
        for rating in _STAR_ORDER:
            cnt = star_counter.get(rating, 0)
            pct = cnt * 100 // total_replies if total_replies else 0
            bar = _bar(cnt, total_replies)
            lines.append(
                f"      {_STAR_DISPLAY[rating]}  {cnt:3}  {bar:<{_BAR_WIDTH}}  ({pct:3}%)"
            )

    return "\n".join(lines)


def run_stats(store_filter: str | None = None) -> tuple[str, int]:
    """Build the stats string.

    Returns:
        (stats_text, exit_code) — exit_code is 1 when store_filter matches nothing.
    """
    stores = cfg.store_list()
    if store_filter:
        stores = [s for s in stores if s["key"] == store_filter]
        if not stores:
            known = ", ".join(s["key"] for s in cfg.store_list())
            return f"Unknown store key: '{store_filter}'. Known keys: {known}", 1

    generated_at = datetime.now(tz=_JST).strftime("%Y-%m-%d %H:%M JST")
    header_lines = [
        "MEO Automation — Aggregate Statistics",
        f"Generated: {generated_at}",
        "",
    ]
    sections = ["\n".join(header_lines)]
    for store in stores:
        sections.append(_format_store_section(store))

    return "\n\n".join(sections) + "\n", 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Show aggregate statistics for the MEO automation archive."
    )
    parser.add_argument(
        "--store",
        metavar="STORE_KEY",
        help="Show statistics for one store only.",
    )
    args = parser.parse_args()

    text, exit_code = run_stats(store_filter=args.store)
    print(text, end="")
    sys.exit(exit_code)


if __name__ == "__main__":  # pragma: no cover
    main()

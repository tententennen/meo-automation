"""meo-trend — compare two consecutive periods for posts, replies, and star ratings.

Reads the content archive in logs/state.json (written by the daily runner)
and shows period-over-period deltas (this week vs last week, or this month vs
last month) per store. No Google credentials required — reads state.json only.

Usage:
    meo-trend                              # weekly comparison (default)
    meo-trend --period monthly             # month-over-month comparison
    meo-trend --store the_body_kyoto       # single store
    python -m meo.tools.trend
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
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
_DIVIDER = "─" * 46

_STAR_VALUES: dict[str, int] = {
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5,
}

_MONTH_JA = {
    1: "1月", 2: "2月", 3: "3月", 4: "4月",
    5: "5月", 6: "6月", 7: "7月", 8: "8月",
    9: "9月", 10: "10月", 11: "11月", 12: "12月",
}


# ---------------------------------------------------------------------------
# Date-range helpers
# ---------------------------------------------------------------------------

def _weekly_ranges(today: date) -> tuple[date, date, date, date]:
    """Return (cur_start, cur_end, prev_start, prev_end) for two back-to-back 7-day windows.

    The current window ends yesterday (excludes today, which may still be in progress).
    The previous window ends the day before the current window starts.

    Example (today = 2026-07-29):
        current:  2026-07-22 〜 2026-07-28
        previous: 2026-07-15 〜 2026-07-21
    """
    cur_end = today - timedelta(days=1)
    cur_start = cur_end - timedelta(days=6)
    prev_end = cur_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=6)
    return cur_start, cur_end, prev_start, prev_end


def _monthly_ranges(today: date) -> tuple[date, date, date, date]:
    """Return (cur_start, cur_end, prev_start, prev_end) for two consecutive calendar months.

    The current period is the previous complete calendar month.
    The previous period is the month before that.

    Example (today = 2026-07-29):
        current:  2026-06-01 〜 2026-06-30
        previous: 2026-05-01 〜 2026-05-31
    """
    first_of_this_month = today.replace(day=1)
    cur_end = first_of_this_month - timedelta(days=1)
    cur_start = cur_end.replace(day=1)
    prev_end = cur_start - timedelta(days=1)
    prev_start = prev_end.replace(day=1)
    return cur_start, cur_end, prev_start, prev_end


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def _filter_by_date(
    entries: list[dict[str, Any]], start: date, end: date
) -> list[dict[str, Any]]:
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


def _star_value(star_str: str) -> int:
    """Map a star-rating string (e.g. 'FIVE') to its numeric value (1–5), 0 for unknown."""
    return _STAR_VALUES.get(star_str, 0)


def _avg_stars(entries: list[dict[str, Any]]) -> float | None:
    """Return the mean star rating across entries, or None when no valid ratings exist."""
    values = [_star_value(e.get("stars", "")) for e in entries]
    valid = [v for v in values if v > 0]
    if not valid:
        return None
    return round(sum(valid) / len(valid), 1)


def _format_delta_count(cur: int, prev: int) -> str:
    """Return a signed count delta label like '+2 (+40%)', '-1 (-14%)', or '±0'.

    When prev is zero (no baseline), percentage is omitted to avoid division-by-zero
    and misleading '∞%' output.
    """
    delta = cur - prev
    if delta == 0:
        return "±0"
    sign = "+" if delta > 0 else ""
    if prev > 0:
        pct = round(100 * delta / prev)
        pct_sign = "+" if pct > 0 else ""
        return f"{sign}{delta} ({pct_sign}{pct}%)"
    return f"{sign}{delta}"


def _format_delta_stars(cur: float | None, prev: float | None) -> str:
    """Return a signed star-delta like '+0.3', '-0.2', '±0.0', or '—' when data is absent."""
    if cur is None or prev is None:
        return "—"
    delta = round(cur - prev, 1)
    if delta == 0.0:
        return "±0.0"
    return f"+{delta}" if delta > 0 else str(delta)


def _period_label(start: date, end: date, period: str) -> str:
    """Return a human-readable period label.

    Weekly:  '2026-07-22 〜 2026-07-28'
    Monthly: '2026年7月'
    """
    if period == "monthly":
        return f"{start.year}年{_MONTH_JA[start.month]}"
    return f"{start.isoformat()} 〜 {end.isoformat()}"


# ---------------------------------------------------------------------------
# Core run function
# ---------------------------------------------------------------------------

def run_trend(
    period: str = "weekly",
    store_filter: list[str] | None = None,
) -> dict[str, Any]:
    """Compute period-over-period metrics for all (or selected) stores.

    Returns a dict with keys:
        'stores'    — list of per-store metric dicts (see below)
        'cur_start', 'cur_end', 'prev_start', 'prev_end' — date boundaries
        'period'    — the period string ('weekly' or 'monthly')

    Each per-store dict has:
        'store'         — store config dict (name, key, ...)
        'cur_posts'     — filtered list of current-period post entries
        'prev_posts'    — filtered list of previous-period post entries
        'cur_replies'   — filtered list of current-period reply entries
        'prev_replies'  — filtered list of previous-period reply entries
        'cur_avg_stars' — float|None average star rating for current period
        'prev_avg_stars'— float|None average star rating for previous period
    """
    today = datetime.now(tz=_JST).date()
    if period == "monthly":
        cur_start, cur_end, prev_start, prev_end = _monthly_ranges(today)
    else:
        cur_start, cur_end, prev_start, prev_end = _weekly_ranges(today)

    stores = cfg.store_list()
    if store_filter:
        stores = [s for s in stores if s["key"] in store_filter]

    store_results: list[dict[str, Any]] = []
    for store in stores:
        key = store["key"]
        all_posts = get_post_history(key)
        all_replies = get_reply_history(key)
        cur_posts = _filter_by_date(all_posts, cur_start, cur_end)
        prev_posts = _filter_by_date(all_posts, prev_start, prev_end)
        cur_replies = _filter_by_date(all_replies, cur_start, cur_end)
        prev_replies = _filter_by_date(all_replies, prev_start, prev_end)
        store_results.append({
            "store": store,
            "cur_posts": cur_posts,
            "prev_posts": prev_posts,
            "cur_replies": cur_replies,
            "prev_replies": prev_replies,
            "cur_avg_stars": _avg_stars(cur_replies),
            "prev_avg_stars": _avg_stars(prev_replies),
        })

    return {
        "stores": store_results,
        "cur_start": cur_start,
        "cur_end": cur_end,
        "prev_start": prev_start,
        "prev_end": prev_end,
        "period": period,
    }


# ---------------------------------------------------------------------------
# Output formatter
# ---------------------------------------------------------------------------

def _format_output(result: dict[str, Any]) -> str:
    """Build the full text output for the trend report."""
    period = result["period"]
    cur_start: date = result["cur_start"]
    cur_end: date = result["cur_end"]
    prev_start: date = result["prev_start"]
    prev_end: date = result["prev_end"]

    period_label_ja = "週次比較" if period == "weekly" else "月次比較"
    cur_label = "今週" if period == "weekly" else "前月"
    prev_label = "先週" if period == "weekly" else "前々月"

    cur_period_str = _period_label(cur_start, cur_end, period)
    prev_period_str = _period_label(prev_start, prev_end, period)

    lines: list[str] = [
        f"MEO Automation — トレンドレポート ({period_label_ja})",
        "",
        f"  当期 ({cur_label}): {cur_period_str}",
        f"  前期 ({prev_label}): {prev_period_str}",
        "",
    ]

    total_cur_posts = 0
    total_prev_posts = 0
    total_cur_replies = 0
    total_prev_replies = 0

    for m in result["stores"]:
        store = m["store"]
        cur_p = len(m["cur_posts"])
        prev_p = len(m["prev_posts"])
        cur_r = len(m["cur_replies"])
        prev_r = len(m["prev_replies"])
        cur_avg: float | None = m["cur_avg_stars"]
        prev_avg: float | None = m["prev_avg_stars"]

        post_delta = _format_delta_count(cur_p, prev_p)
        reply_delta = _format_delta_count(cur_r, prev_r)
        star_delta = _format_delta_stars(cur_avg, prev_avg)

        cur_avg_str = f"★{cur_avg}" if cur_avg is not None else "—"
        prev_avg_str = f"★{prev_avg}" if prev_avg is not None else "—"

        lines.append(_DIVIDER)
        lines.append(f"{store['name']} ({store['key']})")
        lines.append(f"  \U0001f4dd 投稿:  当期 {cur_p}件  前期 {prev_p}件  →  {post_delta}")
        lines.append(f"  \U0001f4ac 返信:  当期 {cur_r}件  前期 {prev_r}件  →  {reply_delta}")
        lines.append(f"  ⭐ 評価:  当期 {cur_avg_str}  前期 {prev_avg_str}  →  {star_delta}")

        total_cur_posts += cur_p
        total_prev_posts += prev_p
        total_cur_replies += cur_r
        total_prev_replies += prev_r

    post_total_delta = _format_delta_count(total_cur_posts, total_prev_posts)
    reply_total_delta = _format_delta_count(total_cur_replies, total_prev_replies)
    lines.append(_DIVIDER)
    lines.append(
        f"合計: 投稿 当期{total_cur_posts}件 前期{total_prev_posts}件 ({post_total_delta})"
        f",  返信 当期{total_cur_replies}件 前期{total_prev_replies}件 ({reply_total_delta})"
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Show period-over-period post, reply, and star-rating trends.\n"
            "Reads state.json only — no Google credentials required."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--period",
        choices=["weekly", "monthly"],
        default="weekly",
        help="Comparison window: 'weekly' (last 7 days vs prior 7 days) "
             "or 'monthly' (last calendar month vs month before). Default: weekly.",
    )
    parser.add_argument(
        "--store",
        metavar="STORE_KEY",
        nargs="+",
        help=(
            "Show trend only for these store key(s). Defaults to all stores.\n"
            "Keys: the_body_osaka_shinsaibashi, the_body_kyoto, mybear_studio_kyoto"
        ),
    )
    args = parser.parse_args()

    stores = cfg.store_list()
    known_keys = {s["key"] for s in stores}
    if args.store:
        unknown = [k for k in args.store if k not in known_keys]
        if unknown:
            print(
                f"Unknown store key(s): {unknown}. Valid keys: {sorted(known_keys)}",
                file=sys.stderr,
            )
            sys.exit(1)

    result = run_trend(period=args.period, store_filter=args.store)
    print(_format_output(result))


if __name__ == "__main__":  # pragma: no cover
    main()

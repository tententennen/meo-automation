"""meo-calendar — daily posting calendar per store.

Shows which days had a 最新情報 post for each store over the last N days,
grouped in weekly chunks for easy scanning.  Highlights any missed days
and prints the posting rate per store.

Reads post_history from logs/state.json — no Google credentials needed.

Usage:
    meo-calendar                           # last 30 days, all stores
    meo-calendar --days 14                 # last 14 days
    meo-calendar --store the_body_kyoto    # single store
    meo-calendar --output logs/calendar.txt
    python -m meo.tools.calendar
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
from ..state import get_post_history

_JST = ZoneInfo("Asia/Tokyo")
_POSTED = "●"
_NOT_POSTED = "○"
_WEEK_SIZE = 7  # symbols per group (visual week)


def _date_range(days: int) -> tuple[date, date]:
    """Return (start, end) for the last ``days`` complete days in JST (excluding today)."""
    today = datetime.now(tz=_JST).date()
    end = today - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    return start, end


def _posted_dates(store_key: str, start: date, end: date) -> set[date]:
    """Return the set of dates within [start, end] on which a post was archived."""
    history = get_post_history(store_key)
    posted: set[date] = set()
    for entry in history:
        raw = entry.get("date", "")
        try:
            d = date.fromisoformat(raw)
        except (ValueError, TypeError):
            continue
        if start <= d <= end:
            posted.add(d)
    return posted


def _week_chunks(dates: list[date]) -> list[list[date]]:
    """Split an ordered date list into sub-lists of _WEEK_SIZE (last may be shorter)."""
    return [dates[i : i + _WEEK_SIZE] for i in range(0, len(dates), _WEEK_SIZE)]


def _symbols_row(chunks: list[list[date]], posted: set[date]) -> str:
    """Build the compact symbol row: weekly groups separated by a single space."""
    parts = ["".join(_POSTED if d in posted else _NOT_POSTED for d in chunk) for chunk in chunks]
    return " ".join(parts)


def _week_header(chunks: list[list[date]]) -> str:
    """Build a date header aligned under _symbols_row: first date of each chunk, padded."""
    parts = []
    for chunk in chunks:
        if not chunk:
            continue
        first = chunk[0]
        # Label format: "M/DD" (e.g. "7/02" or "12/31")
        label = f"{first.month}/{first.day:02d}"
        # Pad to the width of the chunk so it lines up with the symbols
        parts.append(label.ljust(len(chunk)))
    return " ".join(parts)


def _gap_lines(store_data: list[dict[str, Any]], dates: list[date]) -> list[str]:
    """Return one line per missed date (sorted chronologically), or [] when none."""
    lines: list[str] = []
    for d in dates:
        stores_missing = [
            sd["store"]["key"]
            for sd in store_data
            if d not in sd["posted_dates"]
        ]
        for key in stores_missing:
            lines.append(f"  {d.isoformat()} ({key})")
    return lines


def run_calendar(
    *,
    days: int = 30,
    store_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Compute calendar data for the requested stores and date range.

    Args:
        days: How many complete days to include (1–30; default 30).
        store_keys: Limit to these store keys, or None for all stores.

    Returns:
        Dict with:
            start: date — first day of the window
            end:   date — last day (yesterday in JST)
            store_data: list of dicts, one per store:
                store:        store config dict from stores.yaml
                posted_dates: set[date] of dates with a post in the window
                count:        number of days with a post
                total:        total days in the window (== days arg)

    Raises:
        ValueError: if any requested store key is not in stores.yaml.
    """
    start, end = _date_range(days)
    all_stores = cfg.store_list()

    if store_keys is not None:
        known = {s["key"] for s in all_stores}
        unknown = [k for k in store_keys if k not in known]
        if unknown:
            raise ValueError(
                f"Unknown store key(s): {unknown}. "
                f"Valid keys: {sorted(known)}"
            )
        stores = [s for s in all_stores if s["key"] in store_keys]
    else:
        stores = all_stores

    store_data: list[dict[str, Any]] = []
    for store in stores:
        key = store["key"]
        posted = _posted_dates(key, start, end)
        store_data.append(
            {
                "store": store,
                "posted_dates": posted,
                "count": len(posted),
                "total": days,
            }
        )

    return {"start": start, "end": end, "store_data": store_data}


def _format_output(data: dict[str, Any]) -> str:
    """Format the calendar as a human-readable string."""
    start: date = data["start"]
    end: date = data["end"]
    store_data: list[dict[str, Any]] = data["store_data"]

    days = (end - start).days + 1
    dates = [start + timedelta(days=i) for i in range(days)]
    chunks = _week_chunks(dates)

    week_hdr = _week_header(chunks)

    # Width of the symbols + spaces row (used to indent the week header)
    # Each store row: "<name>  <symbols>  <rate>"
    # We compute max name display-length naively (ASCII assumption for alignment)
    max_name_len = max((len(sd["store"]["name"]) for sd in store_data), default=0)
    name_col = max(max_name_len, 16)
    indent = " " * (name_col + 2)

    lines: list[str] = [
        "MEO Automation — 投稿カレンダー",
        f"{start.isoformat()} 〜 {end.isoformat()} (直近{days}日)",
        "",
        indent + week_hdr,
    ]

    for sd in store_data:
        name = sd["store"]["name"]
        posted: set[date] = sd["posted_dates"]
        count = sd["count"]
        total = sd["total"]

        symbols = _symbols_row(chunks, posted)
        pct = round(100 * count / total) if total > 0 else 0
        rate_str = f"{count}/{total} ({pct:3d}%)"
        lines.append(f"{name:<{name_col}}  {symbols}  {rate_str}")

    # Overall total
    total_count = sum(sd["count"] for sd in store_data)
    total_possible = sum(sd["total"] for sd in store_data)
    total_pct = round(100 * total_count / total_possible) if total_possible > 0 else 0

    lines.append("")
    lines.append(f"全店舗合計: {total_count}/{total_possible} ({total_pct}%)")

    # Gap list — only shown when gaps exist
    gap_lines = _gap_lines(store_data, dates)
    if gap_lines:
        lines.append("")
        lines.append("投稿なしの日:")
        lines.extend(gap_lines)

    lines.append("")
    lines.append(f"凡例: {_POSTED} = 投稿あり  {_NOT_POSTED} = 投稿なし  (スペース = 7日ごとの区切り)")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Show a day-by-day posting calendar for all stores."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        metavar="N",
        help="Number of days to show (1–30; default: 30). "
        "Matches post_history archive size per store.",
    )
    parser.add_argument(
        "--store",
        metavar="KEY",
        nargs="+",
        help="Show only the given store key(s). Defaults to all stores.",
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        help="Also save the output to FILE.",
    )
    args = parser.parse_args()

    if args.days < 1 or args.days > 30:
        print("Error: --days must be between 1 and 30.", file=sys.stderr)
        sys.exit(1)

    try:
        data = run_calendar(days=args.days, store_keys=args.store)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    text = _format_output(data)
    print(text)

    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
        except OSError as exc:
            print(f"Warning: could not write to {args.output}: {exc}", file=sys.stderr)


if __name__ == "__main__":  # pragma: no cover
    main()

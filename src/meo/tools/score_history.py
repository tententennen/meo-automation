"""meo-score-history — daily health-grade trend table.

Reads the score snapshots saved by ``meo-score`` into state.json and
displays them as a compact table: one row per day, one column per store,
grade letter in each cell. No Google credentials needed.

Snapshots are saved automatically each time ``meo-score`` runs without a
``--store`` filter (i.e. during the daily CI step). One entry per date;
duplicate calls on the same date replace the earlier entry.

Usage:
    meo-score-history              # last 14 days, all stores
    meo-score-history --days 30   # last 30 days
    meo-score-history --store the_body_kyoto  # single store column
    meo-score-history --output logs/score_history.txt
    python -m meo.tools.score_history
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
from ..state import get_score_snapshots

_JST = ZoneInfo("Asia/Tokyo")
_DEFAULT_DAYS = 14
_MAX_DAYS = 60
_DIVIDER_CHAR = "─"

_GRADE_LETTER: dict[str, str] = {
    "S": "S",
    "A": "A",
    "B": "B",
    "C": "C",
    "D": "D",
}
_MISSING = "—"

_LEGEND = (
    "凡例: S=完璧  A=良好  B=普通  C=要注意  D=要対応  —=データなし"
)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _date_range(days: int, today: date) -> tuple[date, date]:
    """Return (start, end) covering the last `days` complete days before today.

    Today is excluded so the table only shows full-day data.
    end = yesterday; start = end - (days - 1).
    """
    end = today - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    return start, end


def _dates_in_range(start: date, end: date) -> list[date]:
    """Return a list of dates from end down to start (newest first)."""
    result: list[date] = []
    current = end
    while current >= start:
        result.append(current)
        current -= timedelta(days=1)
    return result


# ---------------------------------------------------------------------------
# Core run function
# ---------------------------------------------------------------------------

def run_score_history(
    days: int = _DEFAULT_DAYS,
    store_filter: list[str] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Return score history for the last N complete days.

    Returns a dict with:
        days            — number of days requested
        start, end      — date range (both inclusive)
        stores          — list of {key, name} dicts (in config order)
        rows            — list of {date, grades} dicts (newest first,
                          only rows inside the date range)
        snapshot_count  — number of rows that have at least one grade
    """
    if today is None:
        today = datetime.now(tz=_JST).date()

    start, end = _date_range(days, today)

    all_stores = cfg.store_list()
    if store_filter:
        all_stores = [s for s in all_stores if s["key"] in store_filter]
    stores = [{"key": s["key"], "name": s["name"]} for s in all_stores]

    raw_snapshots = get_score_snapshots()
    date_to_grades: dict[str, dict[str, str]] = {}
    for snap in raw_snapshots:
        d = snap.get("date", "")
        try:
            parsed = date.fromisoformat(d)
        except (ValueError, TypeError):
            continue
        if start <= parsed <= end:
            date_to_grades[d] = snap.get("grades", {})

    dates = _dates_in_range(start, end)
    rows: list[dict[str, Any]] = []
    for d in dates:
        ds = d.isoformat()
        grades = date_to_grades.get(ds, {})
        rows.append({"date": ds, "grades": grades})

    snapshot_count = sum(1 for r in rows if r["grades"])

    return {
        "days": days,
        "start": start,
        "end": end,
        "stores": stores,
        "rows": rows,
        "snapshot_count": snapshot_count,
    }


# ---------------------------------------------------------------------------
# Output formatter
# ---------------------------------------------------------------------------

def _store_short_name(name: str, width: int = 12) -> str:
    """Truncate store name to `width` chars for column header."""
    if len(name) <= width:
        return name
    return name[:width]


def _format_output(data: dict[str, Any]) -> str:
    """Build the full text score-history table."""
    stores = data["stores"]
    rows = data["rows"]
    start: date = data["start"]
    end: date = data["end"]
    days: int = data["days"]
    snapshot_count: int = data["snapshot_count"]

    col_width = 12
    date_col = 10
    sep = "  "

    header_cells = [_store_short_name(s["name"], col_width) for s in stores]
    store_keys = [s["key"] for s in stores]

    lines: list[str] = [
        "MEO Automation — ヘルススコア履歴",
        f"直近 {days} 日 ({start.isoformat()} 〜 {end.isoformat()})",
        "",
    ]

    if not stores:
        lines.append("（店舗データなし）")
        return "\n".join(lines)

    date_label = "日付"
    header_row = date_label.ljust(date_col) + sep + sep.join(
        h.ljust(col_width) for h in header_cells
    )
    divider = _DIVIDER_CHAR * len(header_row)
    lines.append(header_row)
    lines.append(divider)

    for row in rows:
        cells: list[str] = []
        for key in store_keys:
            grade = row["grades"].get(key)
            symbol = _GRADE_LETTER.get(grade, _MISSING) if grade else _MISSING
            cells.append(symbol.ljust(col_width))
        lines.append(row["date"] + sep + sep.join(cells))

    lines.append(divider)
    lines.append(f"（スナップショット: {snapshot_count}/{days} 日分）")
    lines.append("")
    lines.append(_LEGEND)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Daily health-grade trend table.\n"
            "Reads score snapshots from state.json — no Google credentials required.\n"
            "Snapshots are saved automatically each time meo-score runs without --store."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--days",
        type=int,
        default=_DEFAULT_DAYS,
        metavar="N",
        help=f"Number of complete days to display (1–{_MAX_DAYS}, default {_DEFAULT_DAYS}).",
    )
    parser.add_argument(
        "--store",
        metavar="STORE_KEY",
        nargs="+",
        help=(
            "Show only these store column(s). Defaults to all stores.\n"
            "Keys: the_body_osaka_shinsaibashi, the_body_kyoto, mybear_studio_kyoto"
        ),
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        help="Also write the output to this file (non-fatal if write fails).",
    )
    args = parser.parse_args()

    if not (1 <= args.days <= _MAX_DAYS):
        print(
            f"--days must be between 1 and {_MAX_DAYS}, got {args.days}.",
            file=sys.stderr,
        )
        sys.exit(1)

    all_stores = cfg.store_list()
    known_keys = {s["key"] for s in all_stores}
    if args.store:
        unknown = [k for k in args.store if k not in known_keys]
        if unknown:
            print(
                f"Unknown store key(s): {unknown}. Valid keys: {sorted(known_keys)}",
                file=sys.stderr,
            )
            sys.exit(1)

    today = datetime.now(tz=_JST).date()
    data = run_score_history(days=args.days, store_filter=args.store, today=today)
    output = _format_output(data)
    print(output)

    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(output)
        except OSError as exc:
            import logging
            logging.getLogger(__name__).warning(
                "Could not write to %s: %s (non-fatal).", args.output, exc
            )


if __name__ == "__main__":  # pragma: no cover
    main()

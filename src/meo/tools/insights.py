"""meo-insights — Google Business Profile Performance metrics dashboard.

Fetches daily search impressions, map views, website clicks, direction requests,
and call clicks from the Business Profile Performance API v1 and displays a
period-over-period comparison (current half vs prior half of the requested window).

Requires:
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN
  config/stores.yaml — location_id must be filled in for each store

Usage:
    meo-insights                              # all stores, last 28 days
    meo-insights --days 14                   # last 14 days (7-day comparison)
    meo-insights --store the_body_kyoto      # single store
    meo-insights --json                      # machine-readable JSON
    python -m meo.tools.insights

Exit codes:
    0 — all configured stores fetched successfully (or skipped due to no location_id)
    1 — one or more stores returned an API error
"""

from __future__ import annotations

import argparse
import json
import logging
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
from ..auth import get_credentials
from ..performance import (
    ALL_METRICS,
    METRICS_ACTIONS,
    METRICS_IMPRESSIONS,
    PerformanceClient,
)

logger = logging.getLogger(__name__)

_JST = ZoneInfo("Asia/Tokyo")
_DIVIDER = "─" * 58

_METRIC_LABELS: dict[str, str] = {
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS":   "PC マップ表示",
    "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH": "PC 検索表示",
    "BUSINESS_IMPRESSIONS_MOBILE_MAPS":    "スマホ マップ表示",
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH":  "スマホ 検索表示",
    "BUSINESS_DIRECTION_REQUESTS":         "ルート案内",
    "CALL_CLICKS":                         "電話クリック",
    "WEBSITE_CLICKS":                      "ウェブサイトクリック",
}


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def _sum_period(dated_values: dict[str, int], start: date, end: date) -> int:
    """Sum values in dated_values (keyed by ISO date string) within [start, end]."""
    total = 0
    for d_str, v in dated_values.items():
        try:
            d = date.fromisoformat(d_str)
        except ValueError:
            continue
        if start <= d <= end:
            total += v
    return total


def _fmt_delta(cur: int, prev: int) -> str:
    """Return a compact signed percentage delta string.

    Examples: '+12%', '-8%', '±0%', '—' (when both are zero).
    When prev is 0 but cur > 0, returns the absolute count change to avoid
    misleading '∞%' output.
    """
    if cur == 0 and prev == 0:
        return "—"
    delta = cur - prev
    if delta == 0:
        return "±0%"
    sign = "+" if delta > 0 else ""
    if prev > 0:
        pct = round(100 * delta / prev)
        return f"{sign}{pct}%"
    return f"{sign}{delta}"


# ---------------------------------------------------------------------------
# Core run function
# ---------------------------------------------------------------------------

def run_insights(
    store_filter: list[str] | None = None,
    days: int = 28,
) -> list[dict[str, Any]]:
    """Fetch performance metrics for all (or selected) stores.

    The ``days`` window is split in half: the current period covers the most
    recent half and the prior period covers the half before that.  Yesterday
    is the most recent day included (today may still be in progress).

    Returns a list of per-store dicts:
        key, name       — store identity
        location_id     — configured location_id (may be TODO placeholder)
        skipped         — True when location_id is not configured
        error           — API error message string, or None on success
        metrics_cur     — {metric: count} summed over the current period
        metrics_prev    — {metric: count} summed over the prior period
        cur_start/end   — date boundaries for the current period
        prev_start/end  — date boundaries for the prior period
    """
    today = datetime.now(tz=_JST).date()
    half = max(days // 2, 1)

    cur_end = today - timedelta(days=1)
    cur_start = cur_end - timedelta(days=half - 1)
    prev_end = cur_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=half - 1)

    stores = cfg.store_list()
    if store_filter:
        stores = [s for s in stores if s["key"] in store_filter]

    creds = get_credentials()
    client = PerformanceClient(creds)

    results: list[dict[str, Any]] = []
    for store in stores:
        key = store["key"]
        location_id: str = store.get("location_id", "")

        base: dict[str, Any] = {
            "key": key,
            "name": store["name"],
            "location_id": location_id,
            "cur_start": cur_start,
            "cur_end": cur_end,
            "prev_start": prev_start,
            "prev_end": prev_end,
        }

        if not location_id or "TODO" in location_id:
            results.append(
                {**base, "skipped": True, "error": None, "metrics_cur": {}, "metrics_prev": {}}
            )
            continue

        try:
            raw = client.fetch_daily_metrics(location_id, prev_start, cur_end)
        except Exception as exc:
            logger.warning("[%s] Performance API error: %s", key, exc)
            results.append(
                {**base, "skipped": False, "error": str(exc), "metrics_cur": {}, "metrics_prev": {}}
            )
            continue

        metrics_cur: dict[str, int] = {}
        metrics_prev: dict[str, int] = {}
        for metric in ALL_METRICS:
            dated = raw.get(metric, {})
            metrics_cur[metric] = _sum_period(dated, cur_start, cur_end)
            metrics_prev[metric] = _sum_period(dated, prev_start, prev_end)

        results.append(
            {**base, "skipped": False, "error": None,
             "metrics_cur": metrics_cur, "metrics_prev": metrics_prev}
        )

    return results


# ---------------------------------------------------------------------------
# Output formatter
# ---------------------------------------------------------------------------

def _format_output(
    results: list[dict[str, Any]],
    days: int,
    today: date,
) -> str:
    """Build the human-readable text report."""
    half = max(days // 2, 1)
    lines: list[str] = [
        "MEO Automation — パフォーマンス分析",
        f"生成日時: {today.isoformat()} (JST)  対象期間: 直近 {days} 日間",
        "",
    ]

    if results:
        cur_start: date = results[0]["cur_start"]
        cur_end: date = results[0]["cur_end"]
        prev_start: date = results[0]["prev_start"]
        prev_end: date = results[0]["prev_end"]
        lines.append(f"  当期 ({half} 日): {cur_start.isoformat()} 〜 {cur_end.isoformat()}")
        lines.append(f"  前期 ({half} 日): {prev_start.isoformat()} 〜 {prev_end.isoformat()}")
        lines.append("")

    for r in results:
        lines.append(_DIVIDER)
        lines.append(r["name"])

        if r["skipped"]:
            lines.append(
                "  (config/stores.yaml の location_id が未設定 — PROGRESS.md ステップ 6 参照)"
            )
            continue

        if r["error"]:
            short_err = r["error"][:120] + ("…" if len(r["error"]) > 120 else "")
            lines.append(f"  ⚠ APIエラー: {short_err}")
            continue

        cur = r["metrics_cur"]
        prev = r["metrics_prev"]

        # ---- Impressions (map + search) ----
        total_imp_cur = sum(cur.get(m, 0) for m in METRICS_IMPRESSIONS)
        total_imp_prev = sum(prev.get(m, 0) for m in METRICS_IMPRESSIONS)
        delta_imp = _fmt_delta(total_imp_cur, total_imp_prev)
        lines.append(
            f"  表示回数 合計:  当期 {total_imp_cur:>7,}  前期 {total_imp_prev:>7,}  ({delta_imp})"
        )
        for metric in METRICS_IMPRESSIONS:
            label = _METRIC_LABELS.get(metric, metric)
            c, p = cur.get(metric, 0), prev.get(metric, 0)
            lines.append(
                f"    {label:<22} 当期 {c:>7,}  前期 {p:>7,}  ({_fmt_delta(c, p)})"
            )

        lines.append("")

        # ---- Action metrics ----
        for metric in METRICS_ACTIONS:
            label = _METRIC_LABELS.get(metric, metric)
            c, p = cur.get(metric, 0), prev.get(metric, 0)
            lines.append(
                f"  {label:<24} 当期 {c:>7,}  前期 {p:>7,}  ({_fmt_delta(c, p)})"
            )

    lines.append(_DIVIDER)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Google Business Profile パフォーマンス分析。\n"
            "検索・マップ表示回数、ウェブサイト・電話・ルート案内クリック数を表示します。\n"
            "必要: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--days",
        type=int,
        default=28,
        metavar="N",
        help=(
            "取得する日数 (デフォルト: 28)。"
            "当期/前期 各 N/2 日分を比較します。最小値: 2。"
        ),
    )
    parser.add_argument(
        "--store",
        metavar="STORE_KEY",
        nargs="+",
        help=(
            "このストアキーのみ表示。デフォルトは全店舗。\n"
            "Keys: the_body_osaka_shinsaibashi, the_body_kyoto, mybear_studio_kyoto"
        ),
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="機械可読な JSON で出力します。",
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

    if args.days < 2:
        print("--days must be at least 2.", file=sys.stderr)
        sys.exit(1)

    results = run_insights(store_filter=args.store, days=args.days)

    if args.as_json:
        output = []
        for r in results:
            row: dict[str, Any] = dict(r)
            row["cur_start"] = r["cur_start"].isoformat()
            row["cur_end"] = r["cur_end"].isoformat()
            row["prev_start"] = r["prev_start"].isoformat()
            row["prev_end"] = r["prev_end"].isoformat()
            output.append(row)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        sys.exit(0)

    today = datetime.now(tz=_JST).date()
    print(_format_output(results, args.days, today))

    any_error = any(r.get("error") for r in results)
    sys.exit(1 if any_error else 0)


if __name__ == "__main__":  # pragma: no cover
    main()

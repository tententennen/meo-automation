"""meo-score — per-store health scorecard.

Reads state.json and config files offline. Grades each store across four
dimensions: posting rate (7-day), held-review count, average star rating
(30-day), and Drive folder configuration. Emits one letter grade (S/A/B/C/D)
per dimension, an overall grade (worst dimension), and a prioritised
action-item list.

Grades:
    S — Superb (100% / 0 held / ≥4.8★ / Drive configured)
    A — Good
    B — Acceptable (threshold for "healthy")
    C — Needs attention
    D — Critical (action required)

Exit code:
    0 — all stores at grade B or better
    1 — one or more stores below grade B (or unknown store key given)

Usage:
    meo-score                              # all stores
    meo-score --store the_body_kyoto       # single store
    meo-score --slack                      # also post scorecard to Slack
    python -m meo.tools.score
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

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from .. import config as cfg
from ..state import get_held_reviews, get_post_history, get_reply_history, record_score_snapshot

logger = logging.getLogger(__name__)

_JST = ZoneInfo("Asia/Tokyo")
_DIVIDER = "─" * 52

_STAR_VALUES: dict[str, int] = {
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5,
}

_GRADE_ORDER = ["S", "A", "B", "C", "D"]
_UNHEALTHY_THRESHOLD = "B"

_GRADE_LABEL: dict[str, str] = {
    "S": "S  ✨",
    "A": "A  ✓",
    "B": "B  〜",
    "C": "C  ⚠",
    "D": "D  ✗",
}


# ---------------------------------------------------------------------------
# Grade helpers
# ---------------------------------------------------------------------------

def _grade_rank(grade: str) -> int:
    """Return an integer rank for grade (0=S best, 4=D worst); unknown → 4."""
    try:
        return _GRADE_ORDER.index(grade)
    except ValueError:
        return 4


def _worst_grade(grades: list[str]) -> str:
    """Return the single worst (highest-rank) grade from the list."""
    if not grades:
        return "D"
    return max(grades, key=_grade_rank)


def _is_healthy(grade: str) -> bool:
    """Return True when grade is B or better (S, A, or B)."""
    return _grade_rank(grade) <= _grade_rank(_UNHEALTHY_THRESHOLD)


# ---------------------------------------------------------------------------
# Dimension scorers
# ---------------------------------------------------------------------------

def _posting_rate_grade(posts_7d: int) -> str:
    """Grade posting rate over the last 7 complete days (daily target = 7/7)."""
    if posts_7d >= 7:
        return "S"
    if posts_7d == 6:
        return "A"
    if posts_7d == 5:
        return "B"
    if posts_7d >= 3:
        return "C"
    return "D"


def _held_grade(held_count: int) -> str:
    """Grade held-review count (lower is better; 0 held = perfect)."""
    if held_count == 0:
        return "S"
    if held_count == 1:
        return "A"
    if held_count == 2:
        return "B"
    if held_count <= 4:
        return "C"
    return "D"


def _star_grade(avg_stars: float | None) -> str:
    """Grade average star rating over last 30 days (None = no data = D)."""
    if avg_stars is None:
        return "D"
    if avg_stars >= 4.8:
        return "S"
    if avg_stars >= 4.5:
        return "A"
    if avg_stars >= 4.0:
        return "B"
    if avg_stars >= 3.5:
        return "C"
    return "D"


def _drive_grade(folder_id: str) -> str:
    """Grade Drive folder configuration (configured = S; TODO placeholder = D)."""
    if not folder_id or "TODO" in folder_id:
        return "D"
    return "S"


# ---------------------------------------------------------------------------
# Metric extraction helpers
# ---------------------------------------------------------------------------

def _posts_last_7_days(post_history: list[dict[str, Any]], today: date) -> int:
    """Count posts in the last 7 complete days (yesterday back 7 days; today excluded)."""
    end = today - timedelta(days=1)
    start = end - timedelta(days=6)
    count = 0
    for entry in post_history:
        raw = entry.get("date", "")
        try:
            d = date.fromisoformat(raw)
        except (ValueError, TypeError):
            continue
        if start <= d <= end:
            count += 1
    return count


def _avg_stars_30_days(reply_history: list[dict[str, Any]], today: date) -> float | None:
    """Compute average star rating from replies in the last 30 complete days.

    Entries with unknown/empty star values are excluded from the average.
    Returns None when no valid star values exist in the window.
    """
    end = today - timedelta(days=1)
    start = end - timedelta(days=29)
    values: list[int] = []
    for entry in reply_history:
        raw = entry.get("date", "")
        try:
            d = date.fromisoformat(raw)
        except (ValueError, TypeError):
            continue
        if start <= d <= end:
            val = _STAR_VALUES.get(entry.get("stars", ""), 0)
            if val > 0:
                values.append(val)
    if not values:
        return None
    return round(sum(values) / len(values), 1)


# ---------------------------------------------------------------------------
# Action-item builder
# ---------------------------------------------------------------------------

def _action_items(
    held_count: int,
    posts_7d: int,
    avg_stars: float | None,
    held_grade: str,
    post_grade: str,
    star_grade: str,
    drive_grade_val: str,
) -> list[str]:
    """Return a prioritised list of actionable recommendations for one store.

    Items are ordered by urgency: held reviews → Drive setup → post rate → star rating.
    """
    items: list[str] = []

    if not _is_healthy(held_grade):
        items.append(
            f"{held_count}件のレビューが手動返信待ち — "
            "meo-held-reply-draft で返信ドラフトを確認してください"
        )
    elif held_count > 0:
        items.append(
            f"{held_count}件のレビューが保留中 — "
            "meo-held-reply-draft で確認してください"
        )

    if not _is_healthy(drive_grade_val):
        items.append(
            "Drive フォルダ未設定 — "
            "config/stores.yaml の drive_folder_id を入力してください"
        )

    if not _is_healthy(post_grade):
        items.append(
            f"投稿頻度低下: 直近7日 {posts_7d}/7 日投稿 — "
            "daily_run.yml が正しく動作しているか確認してください"
        )

    if not _is_healthy(star_grade):
        if avg_stars is None:
            items.append(
                "返信評価データなし (30日以内) — "
                "レビューへの返信が開始されているか確認してください"
            )
        else:
            items.append(
                f"平均評価が低め (★{avg_stars}/30日) — "
                "最近の返信トーンを見直してください"
            )

    return items


# ---------------------------------------------------------------------------
# Core run function
# ---------------------------------------------------------------------------

def run_score(
    store_filter: list[str] | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Compute health scores for all (or selected) stores.

    Each result dict contains:
        key, name           — store identity
        posts_7d            — post count in last 7 complete days
        avg_stars           — float|None average star rating (30-day window)
        held_count          — number of held reviews from last run's snapshot
        folder_id           — drive_folder_id value from config
        post_grade          — letter grade for posting rate
        held_grade          — letter grade for held-review count
        star_grade          — letter grade for star rating
        drive_grade         — letter grade for Drive configuration
        overall             — worst-dimension grade (overall health)
        healthy             — bool: overall is B or better
        actions             — list[str] of prioritised action items
    """
    if today is None:
        today = datetime.now(tz=_JST).date()

    stores = cfg.store_list()
    if store_filter:
        stores = [s for s in stores if s["key"] in store_filter]

    results: list[dict[str, Any]] = []
    for store in stores:
        key = store["key"]
        folder_id: str = store.get("drive_folder_id", "")

        post_hist = get_post_history(key)
        reply_hist = get_reply_history(key)
        held = get_held_reviews(key)

        posts_7d = _posts_last_7_days(post_hist, today)
        avg_stars = _avg_stars_30_days(reply_hist, today)
        held_count = len(held)

        pg = _posting_rate_grade(posts_7d)
        hg = _held_grade(held_count)
        sg = _star_grade(avg_stars)
        dg = _drive_grade(folder_id)

        overall = _worst_grade([pg, hg, sg, dg])
        actions = _action_items(held_count, posts_7d, avg_stars, hg, pg, sg, dg)

        results.append({
            "key": key,
            "name": store["name"],
            "posts_7d": posts_7d,
            "avg_stars": avg_stars,
            "held_count": held_count,
            "folder_id": folder_id,
            "post_grade": pg,
            "held_grade": hg,
            "star_grade": sg,
            "drive_grade": dg,
            "overall": overall,
            "healthy": _is_healthy(overall),
            "actions": actions,
        })

    return results


# ---------------------------------------------------------------------------
# Output formatter
# ---------------------------------------------------------------------------

def _format_output(results: list[dict[str, Any]], today: date) -> str:
    """Build the full text scorecard output."""
    lines: list[str] = [
        "MEO Automation — 店舗別ヘルススコア",
        f"生成日時: {today.isoformat()} (JST)",
        "",
    ]

    for r in results:
        lines.append(_DIVIDER)
        overall_label = _GRADE_LABEL.get(r["overall"], r["overall"])
        lines.append(f"{r['name']}  ({r['key']})")
        lines.append(f"  総合: {overall_label}")
        lines.append("")

        pg_label = _GRADE_LABEL.get(r["post_grade"], r["post_grade"])
        hg_label = _GRADE_LABEL.get(r["held_grade"], r["held_grade"])
        sg_label = _GRADE_LABEL.get(r["star_grade"], r["star_grade"])
        dg_label = _GRADE_LABEL.get(r["drive_grade"], r["drive_grade"])

        avg_str = f"★{r['avg_stars']}" if r["avg_stars"] is not None else "データなし"
        lines.append(f"  \U0001f4dd 投稿頻度 (7日):  {pg_label}  ({r['posts_7d']}/7 日)")
        lines.append(f"  \U0001f4ac 保留レビュー:    {hg_label}  ({r['held_count']}件)")
        lines.append(f"  ⭐ 平均評価 (30日): {sg_label}  ({avg_str})")
        lines.append(f"  \U0001f4c1 Drive設定:       {dg_label}")

        if r["actions"]:
            lines.append("")
            lines.append("  ▶ アクション:")
            for action in r["actions"]:
                lines.append(f"    • {action}")

    lines.append(_DIVIDER)

    if not results:
        lines.append("（店舗データなし）")
    elif all(r["healthy"] for r in results):
        lines.append("✅ 全店舗のスコアは正常範囲内です (B 以上)")
    else:
        problem_stores = [r["name"] for r in results if not r["healthy"]]
        lines.append(f"⚠️  要対応: {', '.join(problem_stores)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Slack delivery
# ---------------------------------------------------------------------------

def _send_score_to_slack(text: str) -> bool:
    """Post the health scorecard to the Slack webhook.

    Returns True on success, False when the URL is missing or the call fails.
    Failures are logged as warnings and never propagate — callers are
    responsible for deciding whether to exit non-zero based on store health,
    not on notification delivery.
    """
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        logger.debug("SLACK_WEBHOOK_URL not set; skipping Slack notification.")
        return False
    try:
        resp = requests.post(webhook_url, json={"text": text}, timeout=10)
        resp.raise_for_status()
        logger.debug("Health scorecard sent to Slack.")
        return True
    except Exception as exc:
        logger.warning("Score Slack send failed (non-fatal): %s", exc)
        return False


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Per-store health scorecard.\n"
            "Reads state.json and config only — no Google credentials required.\n"
            "Exit 0: all stores at grade B or better.  Exit 1: action needed."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--store",
        metavar="STORE_KEY",
        nargs="+",
        help=(
            "Score only these store key(s). Defaults to all stores.\n"
            "Keys: the_body_osaka_shinsaibashi, the_body_kyoto, mybear_studio_kyoto"
        ),
    )
    parser.add_argument(
        "--slack",
        action="store_true",
        help=(
            "Also send the scorecard to SLACK_WEBHOOK_URL. "
            "No-op when the env var is not set."
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

    today = datetime.now(tz=_JST).date()
    results = run_score(store_filter=args.store, today=today)
    output = _format_output(results, today)
    print(output)

    if args.slack:
        _send_score_to_slack(output)

    if not args.store:
        snapshot_grades = {r["key"]: r["overall"] for r in results}
        record_score_snapshot(today.isoformat(), snapshot_grades)

    if not all(r["healthy"] for r in results):
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()

"""meo-next — what will the next scheduled run do?

Reads state.json and config files offline — no Google credentials needed.
The "next scheduled run" defaults to 09:00 JST:
  - Before 09:00 JST: today's run (hasn't fired yet)
  - At or after 09:00 JST: tomorrow's run (today's has already fired)

Shows for each store:
  • 投稿 — will it post or skip, with reason
  • 時間帯 — is the scheduled time within the posting window?
  • Drive — is the Drive folder configured?
  • 保留 — how many reviews are held for manual reply?

Usage:
    meo-next                                # all stores
    meo-next --store the_body_kyoto         # single store
    meo-next --date 2026-08-08              # simulate a specific run date
    meo-next --output logs/next.txt
    python -m meo.tools.next
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from .. import config as cfg
from ..state import get_held_reviews, get_last_post_date

_JST = ZoneInfo("Asia/Tokyo")
_SCHEDULED_TIME = time(9, 0)   # GitHub Actions fires at 0 UTC = 09:00 JST
_TIME_WINDOW_PAT = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")
_DIVIDER = "─" * 52


def _check_time_window(window_str: str | None, check_time: time) -> bool:
    """Return True if check_time falls within the posting window.

    Returns True when window_str is None/empty (no restriction).
    Handles midnight-crossing windows (e.g. '22:00-06:00').
    Returns True on any parse failure so a misconfigured window does not
    silently block the preview — the same defensive behaviour as posts.py.
    """
    if not window_str:
        return True
    m = _TIME_WINDOW_PAT.match(window_str)
    if not m:
        return True
    sh, sm, eh, em = (int(x) for x in m.groups())
    try:
        start, end = time(sh, sm), time(eh, em)
    except ValueError:
        return True
    if start <= end:
        return start <= check_time <= end
    # Midnight-crossing window: active from start→midnight and midnight→end.
    return check_time >= start or check_time <= end


def _next_run_date(now: datetime | None = None) -> date:
    """Return the date of the next 09:00 JST scheduled run.

    Before 09:00 JST → today (run hasn't fired yet).
    At or after 09:00 JST → tomorrow (today's has already fired).
    """
    if now is None:
        now = datetime.now(tz=_JST)
    today = now.date()
    current_time = now.time().replace(second=0, microsecond=0)
    if current_time < _SCHEDULED_TIME:
        return today
    return today + timedelta(days=1)


def run_next(
    stores: list[dict[str, Any]],
    next_date: date | None = None,
    scheduled_time: time | None = None,
) -> dict[str, Any]:
    """Compute what the next scheduled run would do for each store.

    Args:
        stores:         Store list from config.store_list().
        next_date:      Simulated run date (default: derived from current JST time).
        scheduled_time: Simulated run time for window check (default: 09:00 JST).

    Returns:
        {
            "next_run_date":      str,   # ISO date
            "next_run_time_jst":  str,   # "HH:MM"
            "stores":             list[dict],
        }
    Each store dict has keys:
        store_key, name, post_action ("post"|"skip"|"skip_window"),
        last_post (ISO str or None), cadence_days (int),
        next_post_due (ISO str or None), days_until_due (int),
        time_window (str or None), time_window_ok (bool),
        drive_configured (bool), held_review_count (int).
    """
    if next_date is None:
        next_date = _next_run_date()
    if scheduled_time is None:
        scheduled_time = _SCHEDULED_TIME

    store_results: list[dict[str, Any]] = []
    for store in stores:
        store_key = store["key"]
        store_defaults = cfg.effective_defaults(store)
        cadence_days: int = store_defaults.get("post_cadence_days", 1)
        window_str: str | None = store_defaults.get("post_time_window_jst")
        folder_id: str = store.get("drive_folder_id", "")
        drive_configured = bool(folder_id) and "TODO" not in folder_id

        last_post_str = get_last_post_date(store_key)
        if not last_post_str:
            post_due = True
            last_post = None
            next_post_due = None
            days_until_due = 0
        else:
            try:
                last_date = date.fromisoformat(last_post_str)
            except ValueError:
                post_due = True
                last_post = None
                next_post_due = None
                days_until_due = 0
            else:
                due_date = last_date + timedelta(days=cadence_days)
                post_due = next_date >= due_date
                last_post = last_post_str
                if post_due:
                    next_post_due = None
                    days_until_due = 0
                else:
                    next_post_due = due_date.isoformat()
                    days_until_due = (due_date - next_date).days

        time_window_ok = _check_time_window(window_str, scheduled_time)

        if not post_due:
            post_action = "skip"
        elif not time_window_ok:
            post_action = "skip_window"
        else:
            post_action = "post"

        held_count = len(get_held_reviews(store_key))

        store_results.append({
            "store_key": store_key,
            "name": store["name"],
            "post_action": post_action,
            "last_post": last_post,
            "cadence_days": cadence_days,
            "next_post_due": next_post_due,
            "days_until_due": days_until_due,
            "time_window": window_str,
            "time_window_ok": time_window_ok,
            "drive_configured": drive_configured,
            "held_review_count": held_count,
        })

    return {
        "next_run_date": next_date.isoformat(),
        "next_run_time_jst": scheduled_time.strftime("%H:%M"),
        "stores": store_results,
    }


def _format_output(result: dict[str, Any]) -> str:
    next_date = result["next_run_date"]
    time_str = result["next_run_time_jst"]
    stores = result["stores"]

    lines: list[str] = [
        "MEO Automation — 次回実行プレビュー",
        f"次回スケジュール実行: {next_date} {time_str} JST",
        "",
    ]

    post_count = sum(1 for s in stores if s["post_action"] == "post")

    for sr in stores:
        lines.append(_DIVIDER)
        lines.append(f"{sr['name']}  ({sr['store_key']})")

        action = sr["post_action"]
        last = sr["last_post"]
        cadence = sr["cadence_days"]

        if action == "post":
            reason = "初回 — 投稿履歴なし" if last is None else f"最終: {last}、cadence: {cadence}日"
            lines.append(f"  📝 投稿:   ✅ 実行予定  ({reason})")
        elif action == "skip":
            due = sr["next_post_due"]
            days = sr["days_until_due"]
            lines.append(f"  📝 投稿:   ⏭ スキップ  (最終: {last}、次回: {due}、あと{days}日)")
        else:  # skip_window
            window = sr["time_window"] or "—"
            lines.append(f"  📝 投稿:   ⏰ 時間帯外  ({window} — {time_str} は範囲外)")

        window = sr["time_window"]
        if window:
            ok_sym = "✅" if sr["time_window_ok"] else "⚠ "
            in_out = "は範囲内" if sr["time_window_ok"] else "は範囲外"
            lines.append(f"  ⏰ 時間帯: {ok_sym} {window} — {time_str} JST {in_out}")
        else:
            lines.append("  ⏰ 時間帯: ✅ 制限なし")

        drive_sym = "✅" if sr["drive_configured"] else "⚠ "
        drive_label = "設定済" if sr["drive_configured"] else "未設定 (TODO placeholder)"
        lines.append(f"  📁 Drive:  {drive_sym} {drive_label}")

        held = sr["held_review_count"]
        if held > 0:
            lines.append(f"  💬 保留:   ⚠  {held}件の手動返信待ちレビュー")
        else:
            lines.append("  💬 保留:   ✅ なし")

    lines.append(_DIVIDER)
    lines.append(f"合計: {post_count}/{len(stores)} 店舗が次回実行で投稿予定")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Show what the next scheduled run (09:00 JST) will do for each store.\n"
            "Reads state.json and config only — no Google credentials required."
        )
    )
    parser.add_argument(
        "--store",
        metavar="STORE_KEY",
        nargs="+",
        help="Check only these store key(s). Defaults to all stores.",
    )
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        dest="run_date",
        help=(
            "Simulate the next run at this date "
            "(default: today before 09:00 JST, tomorrow otherwise)."
        ),
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        help="Also save the output to FILE (UTF-8).",
    )
    args = parser.parse_args()

    stores = cfg.store_list()
    if args.store:
        known = {s["key"] for s in stores}
        unknown = [k for k in args.store if k not in known]
        if unknown:
            print(
                f"Unknown store key(s): {unknown}. Valid keys: {sorted(known)}",
                file=sys.stderr,
            )
            sys.exit(1)
        stores = [s for s in stores if s["key"] in args.store]

    next_date: date | None = None
    if args.run_date:
        try:
            next_date = date.fromisoformat(args.run_date)
        except ValueError:
            print(
                f"Invalid date: {args.run_date!r}. Use YYYY-MM-DD format.",
                file=sys.stderr,
            )
            sys.exit(1)

    result = run_next(stores, next_date=next_date)
    output = _format_output(result)
    print(output)

    if args.output:
        out_path = Path(args.output)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(output, encoding="utf-8")
        except OSError as exc:
            print(f"Warning: could not write {out_path}: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    main()

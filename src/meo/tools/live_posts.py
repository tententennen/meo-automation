"""meo-live-posts — Query GBP for currently live local posts and reconcile with local state.

Calls the GBP API (read-only) to fetch all currently active local posts for each
configured store, then cross-references them against the local post archive in
state.json so the operator can spot:

  • Posts that are live on GBP but were not made by this tool (manual posts, gaps
    in the local archive caused by a state reset, etc.)
  • Posts recorded in state.json that are no longer live on GBP (expired after
    6 months, deleted manually, or rejected by GBP moderation).
  • The current post count and state breakdown (LIVE / PROCESSING / REJECTED).

Requires Google credentials (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
GOOGLE_REFRESH_TOKEN) — the same credentials used by meo-run.

Usage:
    meo-live-posts                          # all configured stores
    meo-live-posts --store the_body_kyoto   # single store
    meo-live-posts --json                   # machine-readable JSON output
    python -m meo.tools.live_posts

Exit codes:
    0 — all stores checked without error
    1 — one or more stores failed (API error, missing location_id, or auth error)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from .. import config as cfg
from ..auth import get_credentials
from ..business_profile import BusinessProfileClient
from ..state import get_post_history

logger = logging.getLogger(__name__)

_POST_STATE_LABELS: dict[str, str] = {
    "LIVE": "公開中",
    "PROCESSING": "処理中",
    "REJECTED": "却下",
    "UNKNOWN_STATE": "不明",
}

_SEP = "─" * 62


def _parse_create_time(create_time: str) -> str:
    """Return a compact JST date-time string from a GBP ISO-8601 timestamp."""
    try:
        dt = datetime.fromisoformat(create_time.replace("Z", "+00:00"))
        from zoneinfo import ZoneInfo
        dt_jst = dt.astimezone(ZoneInfo("Asia/Tokyo"))
        return dt_jst.strftime("%Y-%m-%d %H:%M JST")
    except Exception:
        return create_time


def _summary_preview(text: str, max_len: int = 80) -> str:
    flat = text.replace("\n", " ").strip()
    return flat[:max_len] + ("…" if len(flat) > max_len else "")


def check_store_live_posts(
    store: dict[str, Any],
    gbp: BusinessProfileClient,
) -> dict[str, Any]:
    """Fetch live posts for one store and reconcile with state.json archive.

    Returns a result dict with keys:
      store_key, store_name, ok, live_posts, state_breakdown,
      tracked_count, untracked_count, expired_count, error (if any)
    """
    store_key = store["key"]
    store_name = store["name"]
    location_id = store.get("location_id", "")

    if not location_id or "TODO" in location_id:
        return {
            "store_key": store_key,
            "store_name": store_name,
            "ok": False,
            "error": "location_id is not yet configured (TODO placeholder in stores.yaml)",
        }

    try:
        live_posts = gbp.list_local_posts(location_id)
    except Exception as exc:
        return {
            "store_key": store_key,
            "store_name": store_name,
            "ok": False,
            "error": str(exc),
        }

    live_names: set[str] = {p.get("name", "") for p in live_posts if p.get("name")}

    state_breakdown: dict[str, int] = {}
    for p in live_posts:
        state = p.get("state", "UNKNOWN_STATE")
        state_breakdown[state] = state_breakdown.get(state, 0) + 1

    archived = get_post_history(store_key)
    archived_names: set[str] = {e["post_name"] for e in archived if e.get("post_name")}

    tracked_count = len(live_names & archived_names)
    untracked_count = len(live_names - archived_names)
    expired_count = len(archived_names - live_names)

    return {
        "store_key": store_key,
        "store_name": store_name,
        "ok": True,
        "live_posts": live_posts,
        "state_breakdown": state_breakdown,
        "tracked_count": tracked_count,
        "untracked_count": untracked_count,
        "expired_count": expired_count,
    }


def _format_text(results: list[dict[str, Any]]) -> str:
    lines: list[str] = ["MEO Live Posts — GBP現在公開中の投稿", ""]
    for r in results:
        lines.append(_SEP)
        lines.append(f"  {r['store_name']}  ({r['store_key']})")
        lines.append(_SEP)
        if not r["ok"]:
            lines.append(f"  ✗ エラー: {r['error']}")
            lines.append("")
            continue

        live_posts: list[dict] = r.get("live_posts", [])
        breakdown: dict[str, int] = r.get("state_breakdown", {})
        total = len(live_posts)
        lines.append(f"  GBP投稿数: {total}")
        for state, count in sorted(breakdown.items()):
            label = _POST_STATE_LABELS.get(state, state)
            lines.append(f"    {label} ({state}): {count}")
        lines.append(
            f"  このツールが追跡: {r['tracked_count']}件 / "
            f"追跡外: {r['untracked_count']}件 / "
            f"アーカイブ済み・公開終了: {r['expired_count']}件"
        )
        lines.append("")
        if live_posts:
            lines.append("  最新10件:")
            for p in live_posts[:10]:
                state = p.get("state", "?")
                label = _POST_STATE_LABELS.get(state, state)
                create_time = _parse_create_time(p.get("createTime", ""))
                summary = _summary_preview(p.get("summary", ""))
                lines.append(f"    [{label}] {create_time}")
                lines.append(f"      {summary}")
        else:
            lines.append("  現在公開中の投稿はありません。")
        lines.append("")
    lines.append(_SEP)
    return "\n".join(lines)


def run_live_posts(stores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Check live GBP posts for each store. Returns per-store result dicts."""
    try:
        creds = get_credentials()
    except EnvironmentError as exc:
        return [{"store_key": "all", "store_name": "all", "ok": False, "error": str(exc)}]

    gbp = BusinessProfileClient(creds)
    return [check_store_live_posts(s, gbp) for s in stores]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query GBP for currently live local posts and reconcile with local state.",
    )
    parser.add_argument(
        "--store",
        nargs="+",
        metavar="STORE_KEY",
        help="Check only the given store key(s).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output machine-readable JSON instead of a human-readable table.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

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

    results = run_live_posts(stores)

    if args.as_json:
        output = [
            {k: v for k, v in r.items() if k != "live_posts"}
            for r in results
        ]
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(_format_text(results))

    if any(not r["ok"] for r in results):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    main()

"""meo-held-reply-draft — generate AI reply drafts for currently held reviews.

When a review's star rating is below ``min_star_autoreply`` the daily runner
holds it for manual reply rather than auto-posting a response.  This command
reads the held-review snapshot from state.json and generates an AI reply draft
for each held review so the owner can copy-paste it into Google Business Profile
without having to write the reply from scratch.

Requirements:
  - ANTHROPIC_API_KEY (or OPENAI_API_KEY for OpenAI provider) — LLM call
  - No Google credentials needed — reads only state.json

Usage:
    meo-held-reply-draft
    meo-held-reply-draft --store the_body_kyoto
    meo-held-reply-draft --output logs/held_drafts.txt
    python -m meo.tools.held_reply_draft
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from .. import config as cfg
from ..content import generate_reply
from ..state import get_held_reviews

_JST = ZoneInfo("Asia/Tokyo")

_STAR_SYMBOLS: dict[str, str] = {
    "FIVE":  "★★★★★",
    "FOUR":  "★★★★☆",
    "THREE": "★★★☆☆",
    "TWO":   "★★☆☆☆",
    "ONE":   "★☆☆☆☆",
}


def _star_symbol(rating: str) -> str:
    return _STAR_SYMBOLS.get(rating.upper() if rating else "", rating or "？")


def _held_to_review_resource(held: dict[str, Any]) -> dict[str, Any]:
    """Convert a held-review state entry to the GBP review resource shape expected by generate_reply()."""
    return {
        "reviewId": held.get("review_id", ""),
        "name": f"held/{held.get('review_id', '')}",
        "reviewer": {"displayName": held.get("reviewer") or "お客様"},
        "starRating": held.get("stars", "FIVE"),
        "comment": held.get("comment", ""),
    }


def run_held_reply_draft(stores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate AI reply drafts for all currently held reviews, per store.

    Returns a list of per-store result dicts.  Stores with no held reviews are
    omitted.  Each dict has:
        store_key (str), store_name (str),
        drafts: list of {held: dict, draft: str, error: str | None}
    """
    results: list[dict[str, Any]] = []
    for store in stores:
        held_list = get_held_reviews(store["key"])
        if not held_list:
            continue
        drafts: list[dict[str, Any]] = []
        for entry in held_list:
            review_resource = _held_to_review_resource(entry)
            try:
                text = generate_reply(review_resource, store)
                drafts.append({"held": entry, "draft": text, "error": None})
            except Exception as exc:
                drafts.append({"held": entry, "draft": "", "error": str(exc)})
        results.append({
            "store_key": store["key"],
            "store_name": store["name"],
            "drafts": drafts,
        })
    return results


def _format_output(results: list[dict[str, Any]]) -> str:
    now = datetime.now(tz=_JST).strftime("%Y-%m-%d %H:%M JST")
    lines: list[str] = [
        "MEO Automation — 保留中レビューへの返信ドラフト",
        f"Generated: {now}",
    ]

    if not results:
        lines.append("\n保留中のレビューはありません。")
        return "\n".join(lines)

    total_drafts = sum(len(r["drafts"]) for r in results)
    divider = "─" * 56

    for r in results:
        lines.append(f"\n{divider}")
        lines.append(f"{r['store_name']}  ({r['store_key']}) — {len(r['drafts'])}件")
        for i, d in enumerate(r["drafts"], 1):
            held = d["held"]
            star = _star_symbol(held.get("stars", ""))
            reviewer = held.get("reviewer") or "（匿名）"
            date_str = held.get("review_date") or held.get("date") or ""
            comment = held.get("comment", "")
            date_part = f"  {date_str}" if date_str else ""

            lines.append(f"\n[{i}/{len(r['drafts'])}]")
            lines.append(f"  {star}  {reviewer}{date_part}")
            if comment:
                lines.append(f"  レビュー: 「{comment}」")
            else:
                lines.append("  レビュー: （コメントなし）")

            lines.append("\n  ▶ 返信ドラフト:")
            if d["error"]:
                lines.append(f"  ERROR: {d['error']}")
            else:
                for draft_line in d["draft"].splitlines():
                    lines.append(f"  {draft_line}")

    lines.append(f"\n{divider}")
    lines.append(f"合計: {total_drafts}件のドラフトを生成しました")
    lines.append("GBP で各レビューを開き、上記のドラフトをコピーして返信してください。")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate AI reply drafts for currently held (low-star) reviews.\n"
            "Reads state.json for held reviews; requires ANTHROPIC_API_KEY for draft generation.\n"
            "No Google credentials needed."
        )
    )
    parser.add_argument(
        "--store",
        metavar="STORE_KEY",
        nargs="+",
        help=(
            "Generate drafts only for these store key(s). Defaults to all stores.\n"
            "Keys: the_body_osaka_shinsaibashi, the_body_kyoto, mybear_studio_kyoto"
        ),
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        help="Also save the output to FILE (UTF-8). Prints to stdout regardless.",
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

    results = run_held_reply_draft(stores)

    if not results:
        print("保留中のレビューはありません。", file=sys.stderr)
        sys.exit(0)

    output = _format_output(results)
    print(output)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"\nSaved to {out_path}", file=sys.stderr)

    had_error = any(d["error"] for r in results for d in r["drafts"])
    sys.exit(1 if had_error else 0)


if __name__ == "__main__":  # pragma: no cover
    main()

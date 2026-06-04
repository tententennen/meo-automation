"""CLI tool: display post and reply history archived in state.json.

Usage:
    meo-report                            # all stores
    meo-report --store the_body_kyoto     # single store
    meo-report --output logs/report.txt   # save to file
    python -m meo.tools.report
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from .. import config as cfg
from ..state import get_post_history, get_reply_history

_STAR_MAP = {
    "ONE": "★☆☆☆☆",
    "TWO": "★★☆☆☆",
    "THREE": "★★★☆☆",
    "FOUR": "★★★★☆",
    "FIVE": "★★★★★",
}
_MAX_PREVIEW = 100  # characters shown from post/reply text


def _stars(rating: str) -> str:
    return _STAR_MAP.get(rating, rating)


def _preview(text: str) -> str:
    text = text.replace("\n", " ").strip()
    return text[:_MAX_PREVIEW] + ("..." if len(text) > _MAX_PREVIEW else "")


def _format_store_section(store: dict[str, Any]) -> str:
    key = store["key"]
    name = store["name"]
    lines = [
        "─" * 62,
        f"  {name}",
        f"  key: {key}",
        "─" * 62,
    ]

    posts = get_post_history(key)
    lines.append(f"\n  最新情報 posts  ({len(posts)} archived, showing last 5)")
    if posts:
        for p in posts[:5]:
            date_str = p.get("date", "?")
            theme = p.get("theme") or "—"
            text_preview = _preview(p.get("text", ""))
            post_name = p.get("post_name", "")
            lines.append(f"\n  [{date_str}]  theme: {theme}")
            lines.append(f"  {text_preview}")
            if post_name:
                lines.append(f"  GBP resource: {post_name}")
    else:
        lines.append("  (no posts archived yet — run the live script first)")

    replies = get_reply_history(key)
    lines.append(f"\n  Review replies  ({len(replies)} archived, showing last 5)")
    if replies:
        for r in replies[:5]:
            date_str = r.get("date", "?")
            reviewer = r.get("reviewer", "?")
            stars = _stars(r.get("stars", ""))
            reply_preview = _preview(r.get("reply", ""))
            lines.append(f"\n  [{date_str}]  {reviewer}  {stars}")
            lines.append(f"  {reply_preview}")
    else:
        lines.append("  (no replies archived yet — run the live script first)")

    return "\n".join(lines)


def run_report(store_filter: str | None = None) -> tuple[str, int]:
    """Build the report string.

    Returns:
        (report_text, exit_code)  — exit_code is 1 when store_filter matches nothing.
    """
    stores = cfg.store_list()
    if store_filter:
        stores = [s for s in stores if s["key"] == store_filter]
        if not stores:
            known = ", ".join(s["key"] for s in cfg.store_list())
            return f"Unknown store key: '{store_filter}'. Known keys: {known}", 1

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    header_lines = [
        "MEO Automation — Content History Report",
        f"Generated: {generated_at}",
        f"Stores:    {', '.join(s['key'] for s in stores)}",
        "",
    ]
    sections = ["\n".join(header_lines)]
    for store in stores:
        sections.append(_format_store_section(store))
    return "\n\n".join(sections) + "\n", 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Show MEO post and reply history.")
    parser.add_argument("--store", metavar="STORE_KEY", help="Show history for one store only.")
    parser.add_argument("--output", metavar="FILE", help="Also save the report to this file path.")
    args = parser.parse_args()

    report, exit_code = run_report(store_filter=args.store)
    print(report, end="")

    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(report)
            print(f"[Report saved to {args.output}]")
        except OSError as exc:
            print(f"[Error saving report: {exc}]", file=sys.stderr)
            sys.exit(1)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()

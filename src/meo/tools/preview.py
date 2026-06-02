"""Generate sample 最新情報 post + review-reply previews for configured stores.

Requires ONLY the LLM API key — no Google credentials needed.
Use this to verify content quality and tune config/content.yaml before
the first live run, or whenever the tone/themes are updated.

Usage:
    python -m meo.tools.preview
    python -m meo.tools.preview --store the_body_kyoto
    python -m meo.tools.preview --output logs/preview.txt
    meo-preview                                           # after pip install -e .
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
except ImportError:
    pass

from .. import config as cfg
from ..content import generate_post, generate_reply

_JST = ZoneInfo("Asia/Tokyo")

# A realistic sample 3-star review used as input to generate_reply previews.
# 3-star is the most instructive: it requires a mix of thanks and addressing concerns.
_SAMPLE_REVIEW: dict[str, Any] = {
    "reviewId": "preview_review",
    "name": "accounts/0/locations/0/reviews/preview_review",
    "reviewer": {"displayName": "お客様"},
    "starRating": "THREE",
    "comment": "スタッフの方は親切でしたが、少し待ち時間が長く感じました。サービス自体は良かったです。",
}


def run_preview(stores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate a post preview and a review-reply preview for each store.

    Errors in individual stores are captured; other stores continue.

    Returns:
        List of result dicts — one per store.
        Each dict always has 'store_key' and 'name'.
        On success: 'post' and 'reply' keys.
        On error:   'post_error' and/or 'reply_error' keys.
    """
    results: list[dict[str, Any]] = []
    for store in stores:
        result: dict[str, Any] = {"store_key": store["key"], "name": store["name"]}
        try:
            result["post"] = generate_post(store)
        except Exception as exc:
            result["post_error"] = str(exc)
        try:
            result["reply"] = generate_reply(_SAMPLE_REVIEW, store)
        except Exception as exc:
            result["reply_error"] = str(exc)
        results.append(result)
    return results


def _format_output(results: list[dict[str, Any]]) -> str:
    now = datetime.now(tz=_JST).strftime("%Y-%m-%d %H:%M JST")
    lines: list[str] = [
        "MEO Automation — Content Preview",
        f"Generated: {now}",
        "=" * 60,
    ]
    for r in results:
        lines.append(f"\n### {r['name']}  ({r['store_key']})")
        lines.append("\n[最新情報 投稿文]")
        if "post" in r:
            lines.append(r["post"])
        else:
            lines.append(f"ERROR: {r.get('post_error', '—')}")
        lines.append("\n[レビュー返信 — サンプル3つ星レビュー]")
        if "reply" in r:
            lines.append(r["reply"])
        else:
            lines.append(f"ERROR: {r.get('reply_error', '—')}")
        lines.append("\n" + "-" * 60)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate sample post + review-reply previews for configured stores.\n"
            "Only ANTHROPIC_API_KEY (or OPENAI_API_KEY) is required — no Google credentials."
        )
    )
    parser.add_argument(
        "--store",
        metavar="STORE_KEY",
        nargs="+",
        help=(
            "Preview only these store key(s). Defaults to all stores.\n"
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

    results = run_preview(stores)
    output = _format_output(results)
    print(output)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"\nSaved to {out_path}", file=sys.stderr)

    had_error = any("post_error" in r or "reply_error" in r for r in results)
    sys.exit(1 if had_error else 0)


if __name__ == "__main__":
    main()

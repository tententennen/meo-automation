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

# Three sample reviews at different star ratings so the owner can verify that
# the AI generates appropriate replies for unhappy, neutral, and happy customers.
# These are used ONLY for preview/testing — never in the live run.
_SAMPLE_REVIEWS: dict[str, dict[str, Any]] = {
    "ONE": {
        "reviewId": "preview_review_1star",
        "name": "accounts/0/locations/0/reviews/preview_review_1star",
        "reviewer": {"displayName": "お客様"},
        "starRating": "ONE",
        "comment": "期待していたほどではありませんでした。スタッフの対応や施術のクオリティに改善の余地があると感じました。",
    },
    "THREE": {
        "reviewId": "preview_review_3star",
        "name": "accounts/0/locations/0/reviews/preview_review_3star",
        "reviewer": {"displayName": "お客様"},
        "starRating": "THREE",
        "comment": "スタッフの方は親切でしたが、少し待ち時間が長く感じました。サービス自体は良かったです。",
    },
    "FIVE": {
        "reviewId": "preview_review_5star",
        "name": "accounts/0/locations/0/reviews/preview_review_5star",
        "reviewer": {"displayName": "お客様"},
        "starRating": "FIVE",
        "comment": "とても素晴らしいサービスでした！スタッフの皆さんも丁寧で、また来たいと思います。ありがとうございました。",
    },
}

_STAR_LABELS = {"ONE": "1★ 低評価", "THREE": "3★ 普通", "FIVE": "5★ 高評価"}


def run_preview(stores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate a post preview and review-reply previews for each store.

    For each store, generates:
    - One 最新情報 post sample
    - Three review reply samples (1★, 3★, and 5★)

    Errors in individual stores or individual star ratings are captured;
    other stores / ratings continue.

    Returns:
        List of result dicts — one per store.
        Each dict always has 'store_key' and 'name'.
        On success:
            'post': str
            'replies': {'ONE': str, 'THREE': str, 'FIVE': str}
        On error:
            'post_error': str  (instead of 'post')
            'reply_errors': {'ONE': str, ...}  (subset for failed ratings)
    """
    results: list[dict[str, Any]] = []
    for store in stores:
        result: dict[str, Any] = {"store_key": store["key"], "name": store["name"]}
        try:
            result["post"] = generate_post(store)
        except Exception as exc:
            result["post_error"] = str(exc)

        replies: dict[str, str] = {}
        reply_errors: dict[str, str] = {}
        for rating, sample in _SAMPLE_REVIEWS.items():
            try:
                replies[rating] = generate_reply(sample, store)
            except Exception as exc:
                reply_errors[rating] = str(exc)

        if replies:
            result["replies"] = replies
        if reply_errors:
            result["reply_errors"] = reply_errors

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

        lines.append("\n[レビュー返信サンプル — 3パターン]")
        replies = r.get("replies", {})
        reply_errors = r.get("reply_errors", {})
        for rating, label in _STAR_LABELS.items():
            lines.append(f"\n▸ {label}")
            if rating in replies:
                lines.append(replies[rating])
            else:
                lines.append(f"ERROR: {reply_errors.get(rating, '—')}")

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

    had_error = any("post_error" in r or bool(r.get("reply_errors")) for r in results)
    sys.exit(1 if had_error else 0)


if __name__ == "__main__":
    main()

"""meo-review-keyword-alert — Slack alert when watchlist keywords appear in held reviews.

Scans the held-review snapshot in logs/state.json for configurable watchlist
keywords.  When any keyword is found in a review comment, the tool fires a Slack
alert categorised by theme (e.g. 清潔感・衛生, 待ち時間・混雑).

This complements meo-review-alert (which flags ALL held reviews) by adding
keyword-level categorisation — letting the owner know not just that manual
reviews are pending, but what specific issue is being raised before it
accumulates into a star-rating decline.

Keywords and categories are defined in config/content.yaml under the
``review_keyword_watchlist`` key (see example below).  The tool is entirely
offline: it reads only logs/state.json — no Google credentials are required.

Exit codes:
  0 — no watchlist keywords found in current held reviews
  1 — at least one watchlist keyword matched (alert sent/printed)

Usage:
    meo-review-keyword-alert               # check all stores, send to Slack
    meo-review-keyword-alert --dry-run     # print without sending to Slack
    meo-review-keyword-alert --store KEY   # check one store only
    python -m meo.tools.review_keyword_alert

config/content.yaml example:
    review_keyword_watchlist:
      - category: "清潔感・衛生"
        keywords: ["清潔感", "汚い", "臭い", "不衛生"]
      - category: "待ち時間・混雑"
        keywords: ["待ち時間", "混んでいる", "混雑", "待たされ"]
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

import requests

from .. import config as cfg
from ..state import get_held_reviews

logger = logging.getLogger(__name__)

# Maximum characters of the review comment shown in the alert per match.
_COMMENT_PREVIEW_LEN = 80


def _load_watchlist() -> list[dict[str, Any]]:
    """Return the review_keyword_watchlist from content.yaml.

    Each entry is expected to have keys ``category`` (str) and ``keywords``
    (list[str]).  Returns an empty list when the key is absent so the tool
    gracefully no-ops when unconfigured.
    """
    try:
        raw = cfg.content().get("review_keyword_watchlist", [])
        if not isinstance(raw, list):
            logger.warning("review_keyword_watchlist in content.yaml is not a list — skipping.")
            return []
        return raw
    except Exception as exc:
        logger.warning("Failed to load review_keyword_watchlist: %s", exc)
        return []


def _find_matches(
    comment: str,
    watchlist: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Return a list of match dicts for every watchlist keyword found in comment.

    Each match has keys: category, keyword.
    A single comment can yield multiple matches across different categories.
    Within a category the first matching keyword wins (one match per category
    per comment) to avoid duplicate category entries.
    """
    matches: list[dict[str, str]] = []
    text = comment.lower()
    for entry in watchlist:
        category = entry.get("category", "")
        keywords = entry.get("keywords", [])
        if not isinstance(keywords, list):
            continue
        for kw in keywords:
            if not kw:
                continue
            if kw.lower() in text:
                matches.append({"category": category, "keyword": kw})
                break  # one match per category per review
    return matches


def scan_store(
    store_key: str,
    store_name: str,
    watchlist: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return keyword-match alert dicts for one store.

    Each returned dict has keys:
      store_key, store_name, review_id, reviewer, stars, comment_preview,
      category, keyword.
    """
    held = get_held_reviews(store_key)
    results: list[dict[str, Any]] = []
    for review in held:
        comment = review.get("comment", "") or ""
        if not comment:
            continue
        matches = _find_matches(comment, watchlist)
        preview = comment[:_COMMENT_PREVIEW_LEN] + ("…" if len(comment) > _COMMENT_PREVIEW_LEN else "")
        for m in matches:
            results.append({
                "store_key": store_key,
                "store_name": store_name,
                "review_id": review.get("review_id", ""),
                "reviewer": review.get("reviewer", ""),
                "stars": review.get("stars", ""),
                "comment_preview": preview,
                "category": m["category"],
                "keyword": m["keyword"],
            })
    return results


def run_keyword_alert(
    stores: list[dict[str, Any]],
    watchlist: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return a flat list of match dicts across all stores.

    When watchlist is None, loads from content.yaml via _load_watchlist().
    """
    if watchlist is None:
        watchlist = _load_watchlist()
    if not watchlist:
        return []
    results: list[dict[str, Any]] = []
    for store in stores:
        results.extend(scan_store(store["key"], store["name"], watchlist))
    return results


def _star_symbol(rating: str) -> str:
    _map = {
        "FIVE":  "★★★★★",
        "FOUR":  "★★★★☆",
        "THREE": "★★★☆☆",
        "TWO":   "★★☆☆☆",
        "ONE":   "★☆☆☆☆",
    }
    return _map.get((rating or "").upper(), rating or "？")


def format_alert(matches: list[dict[str, Any]]) -> str:
    """Format the Slack alert message from a list of match dicts."""
    # Group by (store_key, category) for a compact summary.
    from collections import defaultdict
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for m in matches:
        grouped[(m["store_key"], m["category"])].append(m)

    total_reviews = len({(m["store_key"], m["review_id"]) for m in matches})
    total_stores = len({m["store_key"] for m in matches})

    lines = [
        f"🚨 MEO レビューキーワードアラート — {total_stores}店舗 / {total_reviews}件のレビューでキーワードを検出",
        "",
    ]
    sep = "─" * 48
    for (store_key, category), items in grouped.items():
        lines.append(sep)
        store_name = items[0]["store_name"]
        lines.append(f"{store_name}  ({store_key})")
        lines.append(f"  カテゴリ: {category}")
        for item in items:
            stars = _star_symbol(item["stars"])
            reviewer = item.get("reviewer") or "（匿名）"
            lines.append(f"  {stars} {reviewer}: 「{item['comment_preview']}」")
            lines.append(f"    ↳ マッチキーワード: 「{item['keyword']}」")
    lines.append(sep)
    lines.append("")
    lines.append("早急にご確認のうえ、対応をご検討ください。")
    return "\n".join(lines)


def _send_alert(message: str) -> bool:
    """POST message to SLACK_WEBHOOK_URL; returns True on success."""
    url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not url:
        logger.debug("SLACK_WEBHOOK_URL not set — skipping Slack keyword alert.")
        return False
    try:
        resp = requests.post(url, json={"text": message}, timeout=10)
        resp.raise_for_status()
        return True
    except requests.HTTPError as exc:
        logger.warning("Slack keyword-alert HTTP error: %s", exc)
    except Exception as exc:
        logger.warning("Slack keyword-alert send failed: %s", exc)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Alert via Slack when watchlist keywords appear in held reviews. "
            "Keywords are configured in config/content.yaml under review_keyword_watchlist."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the alert to stdout but do not send to Slack.",
    )
    parser.add_argument(
        "--store",
        nargs="+",
        metavar="STORE_KEY",
        help="Check only the given store key(s).",
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

    watchlist = _load_watchlist()
    if not watchlist:
        print("No review_keyword_watchlist configured in content.yaml — nothing to check.", file=sys.stderr)
        sys.exit(0)

    matches = run_keyword_alert(stores, watchlist=watchlist)

    if not matches:
        print("No watchlist keywords found in current held reviews.", file=sys.stderr)
        sys.exit(0)

    message = format_alert(matches)
    print(message)

    if not args.dry_run:
        _send_alert(message)

    sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()

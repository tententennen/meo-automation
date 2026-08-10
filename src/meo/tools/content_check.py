"""meo-content-check — content quality metrics for archived posts.

Analyzes the archived post history from state.json and reports quality metrics
for each recent post:
  - Full post text (not truncated like meo-report's 100-char preview)
  - Character count vs. max_post_chars target
  - Japanese character ratio (should be ≥ 80% for Japanese-language posts)
  - Opening-phrase repetition across consecutive posts (detects style drift)

Use this to catch AI content quality regressions before they accumulate:
  - AI generating English or garbled output (low JP ratio)
  - Same opening sentence repeating across consecutive posts
  - Posts significantly shorter than the configured target length

Usage:
    meo-content-check                         # last 3 posts per store (default)
    meo-content-check --last 5                # last 5 posts per store
    meo-content-check --store the_body_kyoto  # single store
    meo-content-check --json                  # machine-readable JSON output
    python -m meo.tools.content_check

Exit codes:
    0  — no quality concerns detected
    1  — one or more concerns found (also on unknown --store key)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from .. import config as cfg
from ..state import get_post_history

_JST = ZoneInfo("Asia/Tokyo")

# Unicode ranges that count as "Japanese script".
# Excludes CJK punctuation (U+3000–U+303F) and full-width Latin (U+FF01–U+FF5E)
# since those are ambiguous — punctuation appears in both Japanese and non-Japanese
# text and should not artificially inflate the ratio.
_JP_RANGES: tuple[tuple[int, int], ...] = (
    (0x3040, 0x309F),   # Hiragana
    (0x30A0, 0x30FF),   # Katakana (includes ー, ・)
    (0x3400, 0x4DBF),   # CJK Extension A
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs (kanji)
    (0xF900, 0xFAFF),   # CJK Compatibility Ideographs
)

# Max characters to consider as the "opening phrase" for repetition detection.
# The actual opening phrase is the text up to the first sentence-ending
# punctuation mark within this window (so a 19-char first sentence is still
# detected even though _OPENING_CHARS is 40).
_OPENING_CHARS = 40

# Characters that mark the end of a Japanese sentence.
_SENTENCE_ENDS: frozenset[str] = frozenset("。！？\n")

# Warn when the Japanese character ratio is below this threshold.
_MIN_JP_RATIO = 0.80

# Warn when a post's length is below this fraction of max_post_chars.
# 0.30 catches severely truncated or AI-hallucinated short posts while
# ignoring intentionally brief posts (e.g. a one-sentence announcement).
_MIN_LENGTH_RATIO = 0.30


def _japanese_ratio(text: str) -> float:
    """Return the fraction of characters in text that are Japanese script.

    Counts Hiragana, Katakana, and CJK Unified Ideographs (kanji).
    Spaces and punctuation are not counted as Japanese.
    Returns 0.0 for empty strings.
    """
    if not text:
        return 0.0
    jp_count = sum(
        1 for ch in text if any(lo <= ord(ch) <= hi for lo, hi in _JP_RANGES)
    )
    return jp_count / len(text)


def _opening_phrase(text: str) -> str:
    """Extract the opening phrase of a post for repetition detection.

    Returns the text up to and including the first sentence-ending punctuation
    mark (。！？ or newline) within the first _OPENING_CHARS characters.
    Falls back to the raw first _OPENING_CHARS characters when no sentence
    boundary is found within that window.

    This handles Japanese sentences correctly: a 19-character first sentence
    ending with 。 is captured as the opening even though _OPENING_CHARS is 40.
    """
    for i, ch in enumerate(text[: _OPENING_CHARS + 1]):
        if ch in _SENTENCE_ENDS:
            return text[: i + 1].strip()
    return text[:_OPENING_CHARS].strip()


def _find_repeated_openings(posts: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """Return (i, j) index pairs where posts[i] and posts[j] share an opening phrase.

    posts is ordered most-recent-first (as returned by get_post_history()).
    Each pair (i, j) means posts[i] and posts[j] share the same opening
    sentence — suggesting the AI reused the same structure across runs.
    """
    openings = [_opening_phrase(p.get("text", "")) for p in posts]
    pairs: list[tuple[int, int]] = []
    seen: dict[str, int] = {}
    for j, opening in enumerate(openings):
        if not opening:
            continue
        if opening in seen:
            pairs.append((seen[opening], j))
        else:
            seen[opening] = j
    return pairs


def _post_metrics(post: dict[str, Any], max_chars: int) -> dict[str, Any]:
    """Compute quality metrics for a single archived post entry.

    Returns a dict with:
        date, theme, text, char_count, jp_ratio, concerns (list of strings).
    """
    text = post.get("text", "")
    char_count = len(text)
    jp_ratio = _japanese_ratio(text)
    concerns: list[str] = []

    if max_chars > 0 and char_count < max_chars * _MIN_LENGTH_RATIO:
        concerns.append(
            f"短すぎる可能性 (目標 {max_chars} 文字に対して {char_count} 文字)"
        )
    if jp_ratio < _MIN_JP_RATIO:
        concerns.append(
            f"日本語率が低い ({jp_ratio:.0%}; 目標: {_MIN_JP_RATIO:.0%} 以上)"
        )
    return {
        "date": post.get("date", ""),
        "theme": post.get("theme", ""),
        "text": text,
        "char_count": char_count,
        "jp_ratio": round(jp_ratio, 3),
        "concerns": concerns,
    }


def run_content_check(
    stores: list[dict[str, Any]],
    last_n: int = 3,
) -> list[dict[str, Any]]:
    """Compute content quality metrics for each store's recent posts.

    Args:
        stores: Store dicts from cfg.store_list().
        last_n: Number of most recent posts to analyse per store.

    Returns:
        List of per-store result dicts with keys:
            store_key, name, max_post_chars,
            posts (list of metrics dicts from _post_metrics()),
            repeated_openings (list of (i, j) index pairs),
            has_concerns (bool — True when any post has concerns or any
                          opening repetition is detected).
    """
    results: list[dict[str, Any]] = []
    for store in stores:
        key = store["key"]
        store_defaults = cfg.effective_defaults(store)
        max_chars: int = store_defaults.get("max_post_chars", 500)
        history = get_post_history(key)[:last_n]
        posts_metrics = [_post_metrics(p, max_chars) for p in history]
        repeated = _find_repeated_openings(history)
        has_concerns = any(m["concerns"] for m in posts_metrics) or bool(repeated)
        results.append(
            {
                "store_key": key,
                "name": store["name"],
                "max_post_chars": max_chars,
                "posts": posts_metrics,
                "repeated_openings": repeated,
                "has_concerns": has_concerns,
            }
        )
    return results


def _format_output(results: list[dict[str, Any]], last_n: int) -> str:
    now = datetime.now(tz=_JST).strftime("%Y-%m-%d %H:%M JST")
    sep = "─" * 62
    lines: list[str] = [
        "MEO Automation — Content Quality Check",
        f"Generated: {now}  |  直近 {last_n} 件の投稿を確認",
        sep,
    ]
    for r in results:
        lines.append(f"\n{r['name']}  ({r['store_key']})")
        lines.append(f"  上限: {r['max_post_chars']} 文字")
        posts = r["posts"]
        if not posts:
            lines.append(
                "  (投稿履歴なし — 先に meo-run を実行してください)"
            )
        else:
            for i, m in enumerate(posts, 1):
                date_str = m["date"] or "?"
                theme = m["theme"] or "—"
                jp_pct = f"{m['jp_ratio']:.0%}"
                char_count = m["char_count"]
                flag = "⚠" if m["concerns"] else "✓"
                lines.append(f"\n  [{i}] {date_str}  theme: {theme}")
                lines.append(
                    f"  {flag}  {char_count} 文字  日本語率: {jp_pct}"
                )
                lines.append("  本文:")
                text_lines = m["text"].splitlines() if m["text"] else ["(空)"]
                for tl in text_lines:
                    lines.append(f"    {tl}")
                for concern in m["concerns"]:
                    lines.append(f"  ⚠ {concern}")

        if r["repeated_openings"]:
            lines.append("")
            for i_idx, j_idx in r["repeated_openings"]:
                lines.append(
                    f"  ⚠ 投稿 [{i_idx + 1}] と [{j_idx + 1}] の書き出しが同じです"
                    " — 文体の多様性が低下している可能性があります"
                )

        lines.append(f"\n{sep}")

    overall = (
        "✓ 問題なし"
        if not any(r["has_concerns"] for r in results)
        else "⚠ 確認が必要な投稿があります"
    )
    lines.append(f"\n{overall}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Content quality check for archived posts.\n"
            "Shows full post text, character count, and Japanese script ratio "
            "for each store's recent posts, and flags quality concerns.\n"
            "Exits 1 when any concern is detected."
        )
    )
    parser.add_argument(
        "--store",
        metavar="STORE_KEY",
        nargs="+",
        help="Check only these store key(s). Defaults to all stores.",
    )
    parser.add_argument(
        "--last",
        type=int,
        default=3,
        metavar="N",
        help="Show the last N posts per store (default: 3).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as JSON instead of the formatted text report.",
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

    results = run_content_check(stores, last_n=args.last)

    if args.json_output:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(_format_output(results, last_n=args.last))

    if any(r["has_concerns"] for r in results):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    main()

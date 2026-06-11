"""meo-export — export post/reply history from state.json to CSV.

Reads the content archive written by the daily runner and outputs a
UTF-8-BOM CSV suitable for opening in Excel or Google Sheets.

Usage:
    meo-export posts         [--store STORE_KEY] [--output FILE]
    meo-export replies       [--store STORE_KEY] [--output FILE]
    meo-export held-reviews  [--store STORE_KEY] [--output FILE]
    python -m meo.tools.export posts
    python -m meo.tools.export replies --store the_body_kyoto --output replies.csv
    python -m meo.tools.export held-reviews --output held.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from .. import config as cfg
from .. import state

_POST_FIELDS = ["store_key", "store_name", "date", "theme", "text", "post_name"]
_REPLY_FIELDS = ["store_key", "store_name", "date", "reviewer", "stars", "review_id", "reply"]
_HELD_FIELDS = ["store_key", "store_name", "date", "review_id", "reviewer", "stars", "comment"]


def export_posts(stores: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return CSV rows for the post content archive across the given stores."""
    rows: list[dict[str, str]] = []
    for store in stores:
        key = store["key"]
        for entry in state.get_post_history(key):
            rows.append({
                "store_key": key,
                "store_name": store["name"],
                "date": entry.get("date", ""),
                "theme": entry.get("theme", ""),
                "text": entry.get("text", ""),
                "post_name": entry.get("post_name", ""),
            })
    return rows


def export_held_reviews(stores: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return CSV rows for the held-review snapshot across the given stores.

    Reviews are held when their star rating is below the store's
    ``min_star_autoreply`` threshold.  The snapshot reflects what was held
    during the most recent live run.  Use ``meo-reset held-reviews`` to clear
    it after manually replying on GBP.
    """
    rows: list[dict[str, str]] = []
    for store in stores:
        key = store["key"]
        for entry in state.get_held_reviews(key):
            rows.append({
                "store_key": key,
                "store_name": store["name"],
                "date": entry.get("date", ""),
                "review_id": entry.get("review_id", ""),
                "reviewer": entry.get("reviewer", ""),
                "stars": entry.get("stars", ""),
                "comment": entry.get("comment", ""),
            })
    return rows


def export_replies(stores: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return CSV rows for the review-reply content archive across the given stores."""
    rows: list[dict[str, str]] = []
    for store in stores:
        key = store["key"]
        for entry in state.get_reply_history(key):
            rows.append({
                "store_key": key,
                "store_name": store["name"],
                "date": entry.get("date", ""),
                "reviewer": entry.get("reviewer", ""),
                "stars": entry.get("stars", ""),
                "review_id": entry.get("review_id", ""),
                "reply": entry.get("reply", ""),
            })
    return rows


def _write_csv(
    rows: list[dict[str, str]],
    fieldnames: list[str],
    output: str | None,
) -> None:
    """Write rows as CSV to a file or stdout.

    Files are written with a UTF-8 BOM (utf-8-sig) so Excel auto-detects the
    encoding on Windows and macOS without needing an explicit import step.
    Stdout is written as plain UTF-8 for piping / shell use.
    """
    if output:
        with open(output, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"Exported {len(rows)} row(s) to {output}", file=sys.stderr)
    else:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        sys.stdout.write(buf.getvalue())


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Export MEO post/reply history from state.json to CSV.\n"
            "Open the output in Excel or Google Sheets to review AI-generated content."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "type",
        choices=["posts", "replies", "held-reviews"],
        help=(
            "Which history to export: 'posts', 'replies', or 'held-reviews'. "
            "'held-reviews' shows reviews currently awaiting manual reply."
        ),
    )
    parser.add_argument(
        "--store",
        metavar="STORE_KEY",
        help=(
            "Export only for this store key. "
            "Keys: the_body_osaka_shinsaibashi, the_body_kyoto, mybear_studio_kyoto. "
            "Defaults to all stores."
        ),
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        help=(
            "Write CSV to this file path. "
            "Excel-compatible UTF-8-BOM encoding is used. "
            "Defaults to stdout."
        ),
    )
    args = parser.parse_args()

    stores = cfg.store_list()

    if args.store:
        known_keys = {s["key"] for s in stores}
        if args.store not in known_keys:
            print(
                f"Unknown store key '{args.store}'. "
                f"Valid keys: {sorted(known_keys)}",
                file=sys.stderr,
            )
            sys.exit(1)
        stores = [s for s in stores if s["key"] == args.store]

    if args.type == "posts":
        rows = export_posts(stores)
        fieldnames = _POST_FIELDS
    elif args.type == "replies":
        rows = export_replies(stores)
        fieldnames = _REPLY_FIELDS
    else:
        rows = export_held_reviews(stores)
        fieldnames = _HELD_FIELDS

    if not rows:
        if args.type == "held-reviews":
            print(
                "No held reviews found. Either no reviews are below min_star_autoreply, "
                "or the tool has not run in live mode yet.",
                file=sys.stderr,
            )
        else:
            print(
                "No data found in state.json. "
                "Run the tool at least once (live, not dry-run) to populate history.",
                file=sys.stderr,
            )
        sys.exit(0)

    _write_csv(rows, fieldnames, args.output)


if __name__ == "__main__":
    main()

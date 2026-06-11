"""State reset CLI — selectively clear state.json entries.

Subcommands:
  post-guard      Clear the "already posted today" date guard.
                  The next run will post even if the cadence window has not
                  elapsed — equivalent to using --force once, but permanent
                  (resets the guard rather than bypassing it for one run).
  image-history   Clear the Drive image rotation history.
                  Useful after uploading new photos to a Drive folder so all
                  images are treated as fresh and not deprioritised.
  theme-history   Clear the post theme rotation history.
                  Useful after editing the theme list in content.yaml so old
                  theme names don't block newly added ones from being picked.
  replied-reviews Clear the local replied-review tracking set.
                  Safe — GBP's own reviewReply field remains the authoritative
                  source; this only resets the propagation-lag safety net.
  held-reviews    Clear the held-review snapshot.
                  Use after manually replying to held reviews on GBP so the
                  next `meo-export held-reviews` reflects the resolved state.
                  The snapshot is also refreshed automatically on each daily run.
  all             Clear all of the above at once.

Without --store, each subcommand applies to ALL stores.

Usage:
    meo-reset post-guard                           # clear all stores
    meo-reset post-guard --store the_body_kyoto    # single store
    meo-reset image-history --store mybear_studio_kyoto
    meo-reset held-reviews                         # after replying manually on GBP
    meo-reset all                                  # wipe all state
    meo-reset all --store the_body_kyoto

    python -m meo.tools.reset post-guard
"""

from __future__ import annotations

import argparse
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from .. import config as cfg
from ..state import (
    clear_held_reviews,
    clear_image_history,
    clear_post_guard,
    clear_replied_reviews,
    clear_theme_history,
)

_DESCRIPTIONS: dict[str, str] = {
    "post-guard":      "Clear the 'already posted today' date guard.",
    "image-history":   "Clear Drive image rotation history.",
    "theme-history":   "Clear post theme rotation history.",
    "replied-reviews": "Clear local replied-review tracking set.",
    "held-reviews":    "Clear the held-review snapshot (after replying manually on GBP).",
    "all":             "Clear all of the above.",
}

_SECTION_LABELS: dict[str, str] = {
    "post_guard":      "Post guard",
    "image_history":   "Image history",
    "theme_history":   "Theme history",
    "replied_reviews": "Replied reviews",
    "held_reviews":    "Held reviews",
}


def run_reset(subcommand: str, store_key: str | None = None) -> dict[str, list[str]]:
    """Execute a reset subcommand, returning what was cleared.

    This function does not validate store_key against the config — validation
    is the caller's responsibility (done by main() for the CLI path).

    Args:
        subcommand: One of "post-guard", "image-history", "theme-history",
                    "replied-reviews", or "all".
        store_key:  Limit to this store key; None means all stores.

    Returns:
        Dict mapping section name → list of store keys that were cleared.
    """
    results: dict[str, list[str]] = {}

    if subcommand in ("post-guard", "all"):
        results["post_guard"] = clear_post_guard(store_key)

    if subcommand in ("image-history", "all"):
        results["image_history"] = clear_image_history(store_key)

    if subcommand in ("theme-history", "all"):
        results["theme_history"] = clear_theme_history(store_key)

    if subcommand in ("replied-reviews", "all"):
        results["replied_reviews"] = clear_replied_reviews(store_key)

    if subcommand in ("held-reviews", "all"):
        results["held_reviews"] = clear_held_reviews(store_key)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="meo-reset",
        description="Selectively clear meo-automation state.json entries.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  meo-reset post-guard                        # clear all stores\n"
            "  meo-reset post-guard --store the_body_kyoto # single store\n"
            "  meo-reset image-history                     # after Drive photo uploads\n"
            "  meo-reset all                               # wipe all state\n"
        ),
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    for name, desc in _DESCRIPTIONS.items():
        sp = sub.add_parser(name, help=desc)
        sp.add_argument(
            "--store",
            metavar="STORE_KEY",
            help="Limit to this store key (default: all stores).",
        )

    args = parser.parse_args()
    store_key: str | None = args.store

    if store_key is not None:
        known_keys = {s["key"] for s in cfg.store_list()}
        if store_key not in known_keys:
            print(
                f"Unknown store key: '{store_key}'. "
                f"Valid keys: {', '.join(sorted(known_keys))}",
                file=sys.stderr,
            )
            sys.exit(1)

    results = run_reset(args.subcommand, store_key)

    any_cleared = any(v for v in results.values())
    if not any_cleared:
        target = f"'{store_key}'" if store_key else "any store"
        print(f"Nothing to clear — no matching state entries found for {target}.")
        sys.exit(0)

    scope = f"'{store_key}'" if store_key else "all stores"
    print(f"Reset complete for {scope}:")
    for section_key, cleared in results.items():
        label = _SECTION_LABELS.get(section_key, section_key)
        if cleared:
            print(f"  ✓ {label}: cleared for {', '.join(cleared)}")
        else:
            print(f"  – {label}: nothing to clear")

    sys.exit(0)


if __name__ == "__main__":
    main()

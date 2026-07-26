"""meo-photo-audit — Drive photo inventory status per store.

Shows recently-used image IDs from state.json (offline mode, no credentials)
or the full Drive folder inventory cross-referenced with state.json (live mode).

Offline mode is useful for a quick check of how many images are in the
rotation without requiring any Google credentials.  Live mode shows whether
a folder is running low on fresh photos and warns before the daily post
starts cycling through the same images repeatedly.

Usage:
    meo-photo-audit                         # offline: state.json only
    meo-photo-audit --live                  # live: Drive API (needs credentials)
    meo-photo-audit --store the_body_kyoto  # single-store
    python -m meo.tools.photo_audit
"""

from __future__ import annotations

import argparse
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
from ..state import get_recent_images

_JST = ZoneInfo("Asia/Tokyo")

# Warn when fewer than this many fresh (never-recently-used) photos remain
# in a store's Drive folder.  7 = less than one week of daily fresh photos.
_LOW_PHOTO_WARNING_THRESHOLD = 7


def run_photo_audit(
    stores: list[dict[str, Any]],
    drive: Any = None,
) -> list[dict[str, Any]]:
    """Audit Drive photo inventory for each store.

    Args:
        stores: Store dicts from cfg.store_list().
        drive:  DriveClient instance (optional).  When None the tool runs in
                offline mode and only state.json data is included in the
                results.  When provided the Drive API is queried for each
                configured store's folder.

    Returns:
        List of per-store audit dicts with keys:
          store_key, name, folder_id, folder_configured,
          recent_image_ids, recent_image_count,
          folder_images (None when offline or on Drive error),
          folder_image_count (None when offline or on Drive error),
          fresh_image_count (None when offline or on Drive error),
          warnings.
    """
    results: list[dict[str, Any]] = []
    for store in stores:
        key = store["key"]
        folder_id: str = store.get("drive_folder_id", "")
        folder_configured = bool(folder_id) and "TODO" not in folder_id

        recent_ids = get_recent_images(key)
        warnings: list[str] = []
        folder_images: list[dict[str, Any]] | None = None
        folder_image_count: int | None = None
        fresh_image_count: int | None = None

        if not folder_configured:
            warnings.append(
                "drive_folder_id is not yet configured (TODO placeholder)"
            )

        if drive is not None and folder_configured:
            try:
                folder_images = drive.list_images(folder_id)
                folder_image_count = len(folder_images)
                recent_set = set(recent_ids)
                fresh_image_count = sum(
                    1 for img in folder_images if img["id"] not in recent_set
                )
                if folder_image_count == 0:
                    warnings.append(
                        "Drive folder is empty — posts will go out without a photo"
                    )
                elif fresh_image_count < _LOW_PHOTO_WARNING_THRESHOLD:
                    warnings.append(
                        f"Only {fresh_image_count} fresh photo(s) remain "
                        f"(threshold: {_LOW_PHOTO_WARNING_THRESHOLD}) — "
                        "consider uploading more photos to Drive"
                    )
            except Exception as exc:
                warnings.append(f"Drive API error: {exc}")

        results.append(
            {
                "store_key": key,
                "name": store["name"],
                "folder_id": folder_id,
                "folder_configured": folder_configured,
                "recent_image_ids": recent_ids,
                "recent_image_count": len(recent_ids),
                "folder_images": folder_images,
                "folder_image_count": folder_image_count,
                "fresh_image_count": fresh_image_count,
                "warnings": warnings,
            }
        )
    return results


def _format_output(results: list[dict[str, Any]], *, live: bool) -> str:
    now = datetime.now(tz=_JST).strftime("%Y-%m-%d %H:%M JST")
    mode = "LIVE (Drive API)" if live else "OFFLINE (state.json only)"
    sep = "─" * 52
    lines: list[str] = [
        "MEO Automation — Photo Inventory Audit",
        f"Generated: {now}  |  Mode: {mode}",
        sep,
    ]
    for r in results:
        lines.append(f"\n{r['name']}  ({r['store_key']})")

        if r["folder_configured"]:
            lines.append(f"  Drive folder: ✓  {r['folder_id']}")
        else:
            lines.append("  Drive folder: ✗  NOT CONFIGURED")

        lines.append(
            f"  Recently used (state.json): {r['recent_image_count']} image ID(s)"
        )

        if live:
            if r["folder_images"] is not None:
                used_count = (r["folder_image_count"] or 0) - (r["fresh_image_count"] or 0)
                lines.append(
                    f"  Folder total: {r['folder_image_count']}  "
                    f"→  Fresh: {r['fresh_image_count']}  "
                    f"Recently used: {used_count}"
                )
                if r["folder_images"]:
                    recent_set = set(r["recent_image_ids"])
                    lines.append("  Photos:")
                    for img in sorted(r["folder_images"], key=lambda x: x["name"]):
                        marker = "⟳ used " if img["id"] in recent_set else "✓ fresh"
                        lines.append(f"    {marker}  {img['name']}")
            elif r["folder_configured"]:
                lines.append("  Drive query failed — see warnings below")

        for w in r["warnings"]:
            lines.append(f"  ⚠  {w}")

        lines.append(sep)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Audit Drive photo inventory per store.\n"
            "Offline (default): reads state.json only — no credentials needed.\n"
            "Live (--live): queries Drive API — requires GOOGLE_* env vars."
        )
    )
    parser.add_argument(
        "--store",
        metavar="STORE_KEY",
        nargs="+",
        help="Audit only these store key(s). Defaults to all stores.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "Query Drive API for actual folder contents "
            "(requires GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN)."
        ),
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

    drive = None
    if args.live:
        from ..auth import get_credentials
        from ..drive import DriveClient
        try:
            creds = get_credentials()
            drive = DriveClient(creds)
        except Exception as exc:
            print(f"Failed to initialise Drive client: {exc}", file=sys.stderr)
            sys.exit(1)

    results = run_photo_audit(stores, drive=drive)
    print(_format_output(results, live=args.live))

    if any(r["warnings"] for r in results):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    main()

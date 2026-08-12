"""meo-post-manual — publish a hand-written 最新情報 to a specific store.

Use this when you want to post a special announcement, event update, or seasonal
notice without waiting for the daily AI-generated run.  The post is recorded in
state.json so the cadence guard treats today as "already posted" for that store,
and the scheduled daily runner skips it for the day.

Requirements:
  - GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN — GBP write
    access (also used for Drive access when --photo is given)
  - No LLM API key needed — you supply the post text directly

Usage:
    meo-post-manual --store the_body_kyoto --text "特別なお知らせ..."
    meo-post-manual --store the_body_kyoto --text "..." --photo DRIVE_FILE_ID
    meo-post-manual --store the_body_kyoto --text "..." --cta-url https://example.com
    meo-post-manual --store the_body_kyoto --text "..." --dry-run
    python -m meo.tools.post_manual
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from .. import config as cfg
from ..auth import get_credentials
from ..business_profile import BusinessProfileClient
from ..drive import DriveClient
from ..state import record_post, record_post_content

logger = logging.getLogger(__name__)

_GBP_POST_TEXT_LIMIT = 1500  # GBP local post summary character limit

_VALID_CTA_TYPES = frozenset(["LEARN_MORE", "BOOK", "ORDER", "SHOP", "SIGN_UP", "CALL"])


def run_post_manual(
    store: dict[str, Any],
    text: str,
    gbp: BusinessProfileClient,
    drive: DriveClient,
    *,
    photo_file_id: str | None = None,
    cta_url: str | None = None,
    cta_action_type: str = "LEARN_MORE",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Publish a manually-written 最新情報 post for a single store.

    Args:
        store:           Store dict from config.store_list().
        text:            Post body text (Japanese, ≤1500 chars recommended).
        gbp:             Authenticated BusinessProfileClient.
        drive:           Authenticated DriveClient.
        photo_file_id:   Drive file ID of a specific photo to attach (optional).
        cta_url:         Call-to-action URL (optional).
        cta_action_type: GBP action type string (default: LEARN_MORE).
        dry_run:         If True, log what would happen but make no API writes.

    Returns:
        Result dict with keys: store_key, status, and (on success) post_name.
        status is one of: "posted", "dry_run".

    Raises:
        ValueError: when location_id is not yet configured for the store.
    """
    store_key = store["key"]
    location_id = str(store.get("location_id") or "")

    if not location_id or "TODO" in location_id:
        raise ValueError(
            f"location_id is not configured for store '{store_key}'. "
            "Fill in config/stores.yaml before posting."
        )

    if len(text) > _GBP_POST_TEXT_LIMIT:
        logger.warning(
            "[%s] Post text is %d chars (GBP limit: %d). The API may reject the post.",
            store_key, len(text), _GBP_POST_TEXT_LIMIT,
        )

    # --- Optional photo ---
    media_url: str | None = None
    photo_meta: dict[str, Any] | None = None

    if photo_file_id:
        try:
            photo_meta = drive.get_image_metadata(photo_file_id)
        except Exception as exc:
            logger.warning(
                "[%s] Could not fetch Drive metadata for file %s: %s — posting without photo.",
                store_key, photo_file_id, exc,
            )

        if photo_meta and not dry_run:
            mime_type = photo_meta.get("mimeType", "image/jpeg")
            try:
                image_bytes = drive.download_image(photo_file_id)
                media_url = gbp.upload_media_bytes(location_id, image_bytes, mime_type)
            except Exception as exc:
                fallback = photo_meta.get("webContentLink")
                if fallback:
                    logger.warning(
                        "[%s] Drive→GBP upload failed (%s); using webContentLink fallback.",
                        store_key, exc,
                    )
                    media_url = fallback
                else:
                    logger.warning(
                        "[%s] Drive→GBP upload failed (%s); no fallback available. "
                        "Posting without photo.",
                        store_key, exc,
                    )

    # --- Optional call-to-action ---
    call_to_action: dict[str, str] | None = None
    if cta_url:
        call_to_action = {"actionType": cta_action_type, "url": cta_url}

    # --- Dry run ---
    if dry_run:
        photo_label: str
        if photo_meta:
            photo_label = photo_meta.get("name", photo_file_id or "")
        else:
            photo_label = photo_file_id or "none"
        logger.info(
            "[%s] DRY RUN — would post:\n%s\nPhoto: %s\nCTA: %s",
            store_key, text, photo_label, call_to_action or "none",
        )
        return {
            "store_key": store_key,
            "status": "dry_run",
            "post_text": text,
            "photo_file_id": photo_file_id,
            "call_to_action": call_to_action,
        }

    # --- Live post ---
    result = gbp.create_local_post(location_id, text, media_url, call_to_action=call_to_action)
    record_post(store_key)
    record_post_content(store_key, text, theme=None, post_name=result.get("name"), manual=True)
    logger.info("[%s] Manual post published: %s", store_key, result.get("name"))
    return {
        "store_key": store_key,
        "status": "posted",
        "post_name": result.get("name"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Publish a hand-written 最新情報 post to a specific store.\n"
            "Bypasses AI content generation — you supply the text directly.\n"
            "Records the post in state.json so the daily cadence guard treats\n"
            "today as 'already posted' for this store."
        )
    )
    parser.add_argument(
        "--store",
        required=True,
        metavar="STORE_KEY",
        help=(
            "Store to post to. "
            "Keys: the_body_osaka_shinsaibashi, the_body_kyoto, mybear_studio_kyoto"
        ),
    )
    parser.add_argument(
        "--text",
        required=True,
        metavar="TEXT",
        help="Post body text (Japanese, ≤1500 chars). Quote the value if it contains spaces.",
    )
    parser.add_argument(
        "--photo",
        metavar="DRIVE_FILE_ID",
        default=None,
        help="Drive file ID of the photo to attach (optional). Copy the ID from the Drive URL.",
    )
    parser.add_argument(
        "--cta-url",
        metavar="URL",
        default=None,
        help="Call-to-action URL to attach to the post (optional).",
    )
    parser.add_argument(
        "--cta-type",
        metavar="TYPE",
        default="LEARN_MORE",
        choices=sorted(_VALID_CTA_TYPES),
        help="GBP call-to-action type (default: LEARN_MORE). Has no effect without --cta-url.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be posted without making any API writes.",
    )
    args = parser.parse_args()

    stores = cfg.store_list()
    store_map = {s["key"]: s for s in stores}
    if args.store not in store_map:
        print(
            f"Unknown store key: {args.store!r}. "
            f"Valid keys: {sorted(store_map)}",
            file=sys.stderr,
        )
        sys.exit(1)
    store = store_map[args.store]

    try:
        creds = get_credentials()
    except Exception as exc:
        print(f"Authentication failed: {exc}", file=sys.stderr)
        sys.exit(1)

    gbp = BusinessProfileClient(creds)
    drive = DriveClient(creds)

    try:
        result = run_post_manual(
            store,
            args.text,
            gbp,
            drive,
            photo_file_id=args.photo,
            cta_url=args.cta_url,
            cta_action_type=args.cta_type,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        sys.exit(1)

    prefix = "[DRY RUN] " if result["status"] == "dry_run" else ""
    print(f"{prefix}Posted to {store['name']} ({args.store}).")
    if result.get("post_name"):
        print(f"Post name: {result['post_name']}")


if __name__ == "__main__":  # pragma: no cover
    main()

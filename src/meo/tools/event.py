"""meo-event — create an EVENT-type イベント post on Google Business Profile.

EVENT posts differ from STANDARD (最新情報) and OFFER posts in that they:
  - Represent a concrete event with a title and optional date+time window
  - Support start and end times (hours:minutes) in addition to dates
  - Appear as an event card on the GBP listing

Use this tool for workshops, special classes, guest instructors, anniversary
celebrations, or any time-bounded event.  The owner supplies all content.

Usage:
    meo-event --store STORE_KEY --title TITLE --text TEXT \\
              [--start YYYY-MM-DD] [--end YYYY-MM-DD] \\
              [--start-time HH:MM] [--end-time HH:MM] \\
              [--photo DRIVE_FILE_ID] \\
              [--cta-url URL] [--cta-type TYPE] \\
              [--dry-run]

Examples:
    meo-event --store mybear_studio_kyoto \\
              --title "特別ヨガクラス" \\
              --text "ゲストインストラクターによる特別クラスを開催します！" \\
              --start 2024-10-05 --end 2024-10-05 \\
              --start-time 10:00 --end-time 12:00

    meo-event --store the_body_kyoto \\
              --title "開店5周年記念イベント" \\
              --text "5周年を記念して特別なメニューをご用意しています。" \\
              --start 2024-11-01 --end 2024-11-30 \\
              --cta-url "https://example.com/book" --cta-type BOOK

    meo-event --store the_body_osaka_shinsaibashi \\
              --title "秋の体験フェア" \\
              --text "新メニューの無料体験を実施中！" \\
              --start 2024-10-12 --end 2024-10-13 \\
              --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
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

# GBP hard limit for localPosts.summary.
_GBP_POST_TEXT_LIMIT = 1500

# GBP event title warning threshold (same as offer title limit).
_GBP_EVENT_TITLE_LIMIT = 58

# Date and time format strings.
_DATE_FMT = "%Y-%m-%d"
_TIME_FMT = "%H:%M"


def _parse_date(date_str: str) -> dict[str, int]:
    """Parse 'YYYY-MM-DD' into a GBP Date object dict.

    Raises ValueError when the string is not in the expected format.
    """
    try:
        dt = datetime.strptime(date_str, _DATE_FMT)
    except ValueError:
        raise ValueError(
            f"Date must be in YYYY-MM-DD format, got: {date_str!r}"
        )
    return {"year": dt.year, "month": dt.month, "day": dt.day}


def _parse_time(time_str: str) -> dict[str, int]:
    """Parse 'HH:MM' into a GBP TimeOfDay object dict.

    Raises ValueError when the string is not in the expected format.
    """
    try:
        dt = datetime.strptime(time_str, _TIME_FMT)
    except ValueError:
        raise ValueError(
            f"Time must be in HH:MM format, got: {time_str!r}"
        )
    return {"hours": dt.hour, "minutes": dt.minute}


def run_event(
    store: dict[str, Any],
    title: str,
    text: str,
    gbp: BusinessProfileClient,
    drive: DriveClient,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    photo_file_id: str | None = None,
    cta_url: str | None = None,
    cta_action_type: str = "BOOK",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create an EVENT post for a single store.

    Args:
        store:          Store dict from cfg.store_list().
        title:          Event name (≤58 chars).
        text:           Post body / summary (≤1500 chars).
        gbp:            Authenticated BusinessProfileClient.
        drive:          Authenticated DriveClient.
        start_date:     Event start 'YYYY-MM-DD' (optional).
        end_date:       Event end 'YYYY-MM-DD' (optional).
        start_time:     Event start time 'HH:MM' (optional).
        end_time:       Event end time 'HH:MM' (optional).
        photo_file_id:  Optional Drive file ID for an attached photo.
        cta_url:        Optional call-to-action URL.
        cta_action_type: CTA action type (default: BOOK).
        dry_run:        If True, log what would happen but make no API writes.

    Returns:
        Result dict: status ('posted' | 'dry_run'), store_key, post_name (on live run).

    Raises:
        ValueError: location_id is not configured, or a date/time string is invalid.
    """
    store_key = store["key"]
    location_id = store.get("location_id", "")

    if not location_id or "TODO" in location_id:
        raise ValueError(
            f"[{store_key}] location_id is not configured in config/stores.yaml. "
            "Fill in the real location ID before posting."
        )

    if len(title) > _GBP_EVENT_TITLE_LIMIT:
        logger.warning(
            "[%s] Event title is %d chars (limit %d); GBP may truncate it.",
            store_key, len(title), _GBP_EVENT_TITLE_LIMIT,
        )
    if len(text) > _GBP_POST_TEXT_LIMIT:
        logger.warning(
            "[%s] Post text is %d chars (limit %d chars); GBP may reject the post.",
            store_key, len(text), _GBP_POST_TEXT_LIMIT,
        )

    # Parse date/time strings early so validation errors surface before any API call.
    start_date_obj = _parse_date(start_date) if start_date else None
    end_date_obj = _parse_date(end_date) if end_date else None
    start_time_obj = _parse_time(start_time) if start_time else None
    end_time_obj = _parse_time(end_time) if end_time else None

    # CTA
    call_to_action: dict[str, str] | None = None
    if cta_url:
        call_to_action = {"actionType": cta_action_type, "url": cta_url}

    # --- Photo handling ---
    media_url: str | None = None
    photo_meta: dict[str, Any] | None = None
    if photo_file_id:
        try:
            photo_meta = drive.get_image_metadata(photo_file_id)
        except Exception as exc:
            logger.warning(
                "[%s] Could not fetch Drive photo metadata (%s); posting without photo.",
                store_key, exc,
            )

    if dry_run:
        logger.info(
            "[%s] DRY RUN — would create EVENT post:\n"
            "  Title      : %s\n"
            "  Text       : %s\n"
            "  Start date : %s  Start time: %s\n"
            "  End date   : %s  End time  : %s\n"
            "  Photo      : %s\n"
            "  CTA        : %s",
            store_key, title, text[:80],
            start_date or "—", start_time or "—",
            end_date or "—", end_time or "—",
            photo_meta.get("name") if photo_meta else (photo_file_id or "none"),
            call_to_action or "none",
        )
        return {
            "store_key": store_key,
            "status": "dry_run",
            "title": title,
            "post_text": text,
            "start_date": start_date,
            "end_date": end_date,
            "start_time": start_time,
            "end_time": end_time,
            "photo_file_id": photo_file_id,
            "call_to_action": call_to_action,
        }

    # Download and upload photo (live run only).
    if photo_meta:
        mime_type = photo_meta.get("mimeType", "image/jpeg")
        try:
            image_bytes = drive.download_image(photo_meta["id"])
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
                    "[%s] Drive→GBP upload failed (%s); no fallback URL. Posting without photo.",
                    store_key, exc,
                )

    result = gbp.create_event_post(
        location_id,
        title,
        text,
        start_date=start_date_obj,
        end_date=end_date_obj,
        start_time=start_time_obj,
        end_time=end_time_obj,
        media_url=media_url,
        call_to_action=call_to_action,
    )
    post_name = result.get("name")

    # Record in state so the cadence guard treats today as "already posted".
    record_post(store_key)
    record_post_content(store_key, text, theme=f"EVENT:{title}", post_name=post_name, manual=True)

    logger.info("[%s] Event post created: %s", store_key, post_name)
    return {
        "store_key": store_key,
        "status": "posted",
        "post_name": post_name,
        "title": title,
    }


def main() -> None:  # pragma: no cover
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(
        description=(
            "Create an EVENT-type GBP post (イベント) for a store.\n"
            "All content is supplied by the owner — no AI generation.\n"
            "The post is recorded in state.json so the daily runner skips the store today."
        )
    )
    parser.add_argument("--store", required=True, metavar="STORE_KEY",
                        help="Store key from config/stores.yaml.")
    parser.add_argument("--title", required=True, metavar="TITLE",
                        help=f"Event name (≤{_GBP_EVENT_TITLE_LIMIT} chars).")
    parser.add_argument("--text", required=True, metavar="TEXT",
                        help=f"Post body / summary (≤{_GBP_POST_TEXT_LIMIT} chars).")
    parser.add_argument("--start", dest="start_date", metavar="YYYY-MM-DD",
                        help="Event start date.")
    parser.add_argument("--end", dest="end_date", metavar="YYYY-MM-DD",
                        help="Event end date.")
    parser.add_argument("--start-time", dest="start_time", metavar="HH:MM",
                        help="Event start time (optional, 24-hour format).")
    parser.add_argument("--end-time", dest="end_time", metavar="HH:MM",
                        help="Event end time (optional, 24-hour format).")
    parser.add_argument("--photo", dest="photo_file_id", metavar="DRIVE_FILE_ID",
                        help="Drive file ID for an attached photo (optional).")
    parser.add_argument("--cta-url", metavar="URL",
                        help="Call-to-action URL (optional).")
    parser.add_argument("--cta-type", metavar="TYPE", default="BOOK",
                        help="CTA action type (default: BOOK). Options: BOOK, ORDER, SHOP, LEARN_MORE, SIGN_UP, CALL.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Log what would be posted without making any API write.")
    args = parser.parse_args()

    stores = cfg.store_list()
    known_keys = {s["key"] for s in stores}
    if args.store not in known_keys:
        print(
            f"Unknown store key: {args.store!r}. Valid keys: {sorted(known_keys)}",
            file=sys.stderr,
        )
        sys.exit(1)
    store = next(s for s in stores if s["key"] == args.store)

    try:
        creds = get_credentials()
    except Exception as exc:
        print(f"Authentication failed: {exc}", file=sys.stderr)
        sys.exit(1)

    gbp = BusinessProfileClient(creds)
    drive = DriveClient(creds)

    try:
        result = run_event(
            store,
            args.title,
            args.text,
            gbp,
            drive,
            start_date=args.start_date,
            end_date=args.end_date,
            start_time=args.start_time,
            end_time=args.end_time,
            photo_file_id=args.photo_file_id,
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

    if result["status"] == "dry_run":
        start_label = result["start_date"] or "—"
        if result["start_time"]:
            start_label += f" {result['start_time']}"
        end_label = result["end_date"] or "—"
        if result["end_time"]:
            end_label += f" {result['end_time']}"
        print(
            f"[DRY RUN] Would post EVENT '{result['title']}' to {store['name']}.\n"
            f"  Text  : {result['post_text'][:100]}{'...' if len(result['post_text']) > 100 else ''}\n"
            f"  Start : {start_label}\n"
            f"  End   : {end_label}\n"
            f"  Photo : {result['photo_file_id'] or 'none'}\n"
            f"  CTA   : {result['call_to_action'] or 'none'}"
        )
    else:
        print(f"Event post created for {store['name']}: {result['post_name']}")

    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    main()

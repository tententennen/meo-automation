"""meo-offer — create an OFFER-type 時限キャンペーン post on Google Business Profile.

OFFER posts differ from STANDARD (最新情報) posts in that they:
  - Have a display title and a date range (start + end)
  - Can carry a coupon code, a redemption URL, and terms & conditions
  - Appear in a distinct "Offer" card on the GBP listing

Use this tool for time-limited promotions: seasonal discounts, anniversary
deals, new-customer campaigns.  The owner supplies all content directly.

Usage:
    meo-offer --store STORE_KEY --title TITLE --text TEXT \\
              --start YYYY-MM-DD --end YYYY-MM-DD \\
              [--coupon CODE] [--redeem-url URL] [--terms TEXT] \\
              [--photo DRIVE_FILE_ID] \\
              [--cta-url URL] [--cta-type TYPE] \\
              [--dry-run]

Examples:
    meo-offer --store the_body_kyoto \\
              --title "夏の特別キャンペーン" \\
              --text "今月限定！全メニュー20%オフです。" \\
              --start 2024-08-01 --end 2024-08-31 \\
              --coupon SUMMER20

    meo-offer --store mybear_studio_kyoto \\
              --title "体験レッスン無料" \\
              --text "はじめての方は体験レッスンが無料！" \\
              --start 2024-09-01 --end 2024-09-30 \\
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

# GBP hard limit for offer title.
_GBP_OFFER_TITLE_LIMIT = 58

# Date format expected by --start / --end flags.
_DATE_FMT = "%Y-%m-%d"


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


def run_offer(
    store: dict[str, Any],
    title: str,
    text: str,
    gbp: BusinessProfileClient,
    drive: DriveClient,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    coupon_code: str | None = None,
    redeem_url: str | None = None,
    terms: str | None = None,
    photo_file_id: str | None = None,
    cta_url: str | None = None,
    cta_action_type: str = "LEARN_MORE",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create an OFFER post for a single store.

    Args:
        store:          Store dict from cfg.store_list().
        title:          Offer title (≤58 chars).
        text:           Post body / summary (≤1500 chars).
        gbp:            Authenticated BusinessProfileClient.
        drive:          Authenticated DriveClient.
        start_date:     Offer start 'YYYY-MM-DD' (optional).
        end_date:       Offer end 'YYYY-MM-DD' (optional).
        coupon_code:    Optional coupon / promo code.
        redeem_url:     Optional redemption URL.
        terms:          Optional terms & conditions text.
        photo_file_id:  Optional Drive file ID for an attached photo.
        cta_url:        Optional call-to-action URL.
        cta_action_type: CTA action type (default: LEARN_MORE).
        dry_run:        If True, log what would happen but make no API writes.

    Returns:
        Result dict: status ('posted' | 'dry_run'), store_key, post_name (on live run).

    Raises:
        ValueError: location_id is not configured, or a date string is invalid.
    """
    store_key = store["key"]
    location_id = store.get("location_id", "")

    if not location_id or "TODO" in location_id:
        raise ValueError(
            f"[{store_key}] location_id is not configured in config/stores.yaml. "
            "Fill in the real location ID before posting."
        )

    if len(title) > _GBP_OFFER_TITLE_LIMIT:
        logger.warning(
            "[%s] Offer title is %d chars (limit %d); GBP may truncate it.",
            store_key, len(title), _GBP_OFFER_TITLE_LIMIT,
        )
    if len(text) > _GBP_POST_TEXT_LIMIT:
        logger.warning(
            "[%s] Post text is %d chars (limit %d chars); GBP may reject the post.",
            store_key, len(text), _GBP_POST_TEXT_LIMIT,
        )

    # Parse date strings early so validation errors surface before any API call.
    start_date_obj = _parse_date(start_date) if start_date else None
    end_date_obj = _parse_date(end_date) if end_date else None

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
            "[%s] DRY RUN — would create OFFER post:\n"
            "  Title   : %s\n"
            "  Text    : %s\n"
            "  Dates   : %s → %s\n"
            "  Coupon  : %s\n"
            "  Redeem  : %s\n"
            "  Terms   : %s\n"
            "  Photo   : %s\n"
            "  CTA     : %s",
            store_key, title, text[:80],
            start_date or "—", end_date or "—",
            coupon_code or "—", redeem_url or "—", terms or "—",
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
            "coupon_code": coupon_code,
            "redeem_url": redeem_url,
            "terms": terms,
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

    result = gbp.create_offer_post(
        location_id,
        title,
        text,
        start_date=start_date_obj,
        end_date=end_date_obj,
        coupon_code=coupon_code,
        redeem_url=redeem_url,
        terms=terms,
        media_url=media_url,
        call_to_action=call_to_action,
    )
    post_name = result.get("name")

    # Record in state so the cadence guard treats today as "already posted".
    record_post(store_key)
    record_post_content(store_key, text, theme=f"OFFER:{title}", post_name=post_name, manual=True)

    logger.info("[%s] Offer post created: %s", store_key, post_name)
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
            "Create an OFFER-type GBP post (時限キャンペーン) for a store.\n"
            "All content is supplied by the owner — no AI generation.\n"
            "The post is recorded in state.json so the daily runner skips the store today."
        )
    )
    parser.add_argument("--store", required=True, metavar="STORE_KEY",
                        help="Store key from config/stores.yaml.")
    parser.add_argument("--title", required=True, metavar="TITLE",
                        help=f"Offer title (≤{_GBP_OFFER_TITLE_LIMIT} chars).")
    parser.add_argument("--text", required=True, metavar="TEXT",
                        help=f"Post body / summary (≤{_GBP_POST_TEXT_LIMIT} chars).")
    parser.add_argument("--start", dest="start_date", metavar="YYYY-MM-DD",
                        help="Offer start date.")
    parser.add_argument("--end", dest="end_date", metavar="YYYY-MM-DD",
                        help="Offer end date.")
    parser.add_argument("--coupon", dest="coupon_code", metavar="CODE",
                        help="Coupon / promo code (optional).")
    parser.add_argument("--redeem-url", metavar="URL",
                        help="URL where customers can redeem the offer online (optional).")
    parser.add_argument("--terms", metavar="TEXT",
                        help="Terms & conditions text (optional).")
    parser.add_argument("--photo", dest="photo_file_id", metavar="DRIVE_FILE_ID",
                        help="Drive file ID for an attached photo (optional).")
    parser.add_argument("--cta-url", metavar="URL",
                        help="Call-to-action URL (optional).")
    parser.add_argument("--cta-type", metavar="TYPE", default="LEARN_MORE",
                        help="CTA action type (default: LEARN_MORE). Options: BOOK, ORDER, SHOP, LEARN_MORE, SIGN_UP, CALL.")
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
        result = run_offer(
            store,
            args.title,
            args.text,
            gbp,
            drive,
            start_date=args.start_date,
            end_date=args.end_date,
            coupon_code=args.coupon_code,
            redeem_url=args.redeem_url,
            terms=args.terms,
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
        print(
            f"[DRY RUN] Would post OFFER '{result['title']}' to {store['name']}.\n"
            f"  Text    : {result['post_text'][:100]}{'...' if len(result['post_text']) > 100 else ''}\n"
            f"  Dates   : {result['start_date'] or '—'} → {result['end_date'] or '—'}\n"
            f"  Coupon  : {result['coupon_code'] or '—'}\n"
            f"  Photo   : {result['photo_file_id'] or 'none'}\n"
            f"  CTA     : {result['call_to_action'] or 'none'}"
        )
    else:
        print(f"Offer posted to {store['name']}: {result['post_name']}")

    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    main()

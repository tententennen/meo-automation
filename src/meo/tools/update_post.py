"""meo-update-post — patch the text or CTA of a live GBP local post.

Use meo-live-posts first to find the resource name of the post you want to edit,
then supply at least one of --summary or --cta-url.  Only the named fields are
changed; everything else (photos, event dates, post type, …) is left untouched.

Supported CTA action types (--cta-action):
  BOOK, ORDER, SHOP, LEARN_MORE, SIGN_UP, GET_OFFER, CALL

Requirements:
  - GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN

Usage:
    # Correct a typo in the post body
    meo-update-post --post-name accounts/123/locations/456/localPosts/789 \\
                    --summary "新しい本文テキスト"

    # Update (or add) a CTA button
    meo-update-post --post-name accounts/123/locations/456/localPosts/789 \\
                    --cta-action BOOK --cta-url "https://example.com/booking"

    # Update both at once
    meo-update-post --post-name accounts/123/locations/456/localPosts/789 \\
                    --summary "更新されたテキスト" \\
                    --cta-url "https://example.com/booking"

    # Preview without making any API calls
    meo-update-post --post-name accounts/123/locations/456/localPosts/789 \\
                    --summary "新しいテキスト" --dry-run

    python -m meo.tools.update_post
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from ..auth import get_credentials
from ..business_profile import BusinessProfileClient

logger = logging.getLogger(__name__)

_JST = ZoneInfo("Asia/Tokyo")

_POST_NAME_MARKER = "/localPosts/"

_VALID_CTA_ACTIONS = {
    "BOOK", "ORDER", "SHOP", "LEARN_MORE", "SIGN_UP", "GET_OFFER", "CALL",
}


def _validate_post_name(post_name: str) -> None:
    """Raise ValueError if post_name doesn't look like a GBP localPost resource name."""
    if not post_name or _POST_NAME_MARKER not in post_name:
        raise ValueError(
            f"Post name must contain '{_POST_NAME_MARKER}' "
            f"(e.g. 'accounts/123/locations/456/localPosts/789'). "
            f"Got: {post_name!r}. Run meo-live-posts to find valid post names."
        )


def _validate_cta_action(action: str) -> None:
    """Raise ValueError if the CTA action type is not recognised."""
    if action.upper() not in _VALID_CTA_ACTIONS:
        raise ValueError(
            f"Invalid CTA action: {action!r}. "
            f"Valid values: {', '.join(sorted(_VALID_CTA_ACTIONS))}"
        )


def _parse_update_time(update_time: str) -> str:
    """Convert a GBP ISO-8601 timestamp to a compact JST string."""
    try:
        dt = datetime.fromisoformat(update_time.replace("Z", "+00:00"))
        return dt.astimezone(_JST).strftime("%Y-%m-%d %H:%M JST")
    except Exception:
        return update_time


def _format_update_preview(
    post_name: str,
    summary: str | None,
    cta_action: str | None,
    cta_url: str | None,
) -> str:
    """Return a human-readable summary of what would be changed."""
    lines: list[str] = [f"  Post:  {post_name}"]
    if summary is not None:
        preview = summary.replace("\n", " ")[:120]
        ellipsis = "…" if len(summary) > 120 else ""
        lines.append(f"  Text:  {preview}{ellipsis}")
    if cta_action is not None:
        lines.append(f"  CTA:   {cta_action}")
    if cta_url is not None:
        lines.append(f"  URL:   {cta_url}")
    return "\n".join(lines)


def _format_result(result: dict[str, Any]) -> str:
    """Return a human-readable summary of the updated post resource."""
    lines: list[str] = [f"  Post:  {result.get('name', '?')}"]
    state = result.get("state", "?")
    topic = result.get("topicType", "?")
    lines.append(f"  Type:  {topic}   State: {state}")
    update_time = result.get("updateTime", "")
    if update_time:
        lines.append(f"  Updated: {_parse_update_time(update_time)}")
    summary = result.get("summary", "")
    if summary:
        preview = summary.replace("\n", " ")[:120]
        ellipsis = "…" if len(summary) > 120 else ""
        lines.append(f"  Text:  {preview}{ellipsis}")
    cta = result.get("callToAction", {})
    if cta:
        lines.append(f"  CTA:   {cta.get('actionType', '?')}  {cta.get('url', '')}")
    return "\n".join(lines)


def run_update_post(
    post_name: str,
    gbp: BusinessProfileClient,
    *,
    summary: str | None = None,
    cta_action: str | None = None,
    cta_url: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Patch a specific GBP local post.

    Args:
        post_name:  Full GBP localPost resource name.
        gbp:        Authenticated BusinessProfileClient.
        summary:    New post body text (or None to leave unchanged).
        cta_action: New CTA button type (or None to leave unchanged).
        cta_url:    New CTA destination URL (or None to leave unchanged).
        dry_run:    If True, log intent but make no API call.

    Returns:
        Dict with keys: post_name, status, fields_updated, and (on live run)
        the updated post resource under 'post'.

    Raises:
        ValueError:          on invalid post_name or no fields to update.
        requests.HTTPError:  on GBP API error.
    """
    _validate_post_name(post_name)
    if cta_action is not None:
        _validate_cta_action(cta_action)

    fields: list[str] = []
    if summary is not None:
        fields.append("summary")
    if cta_action is not None or cta_url is not None:
        fields.append("callToAction")

    if not fields:
        raise ValueError(
            "Nothing to update. Supply at least --summary or --cta-url."
        )

    if dry_run:
        logger.info(
            "DRY RUN — would PATCH %s (fields: %s)", post_name, ", ".join(fields)
        )
        return {
            "post_name": post_name,
            "status": "dry_run",
            "fields_updated": fields,
        }

    updated = gbp.update_local_post(
        post_name,
        summary=summary,
        cta_action=cta_action,
        cta_url=cta_url,
    )
    logger.info("Updated GBP post: %s (fields: %s)", post_name, ", ".join(fields))
    return {
        "post_name": post_name,
        "status": "updated",
        "fields_updated": fields,
        "post": updated,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Patch the text or CTA of a live GBP local post.\n"
            "Run meo-live-posts first to find the post resource name.\n"
            "Only the supplied fields are changed; everything else is left intact."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--post-name",
        required=True,
        metavar="RESOURCE_NAME",
        help=(
            "Full GBP localPost resource name, e.g. "
            "'accounts/123/locations/456/localPosts/789'. "
            "Run meo-live-posts to find post names."
        ),
    )
    parser.add_argument(
        "--summary",
        metavar="TEXT",
        help="New post body text. Replaces the existing text entirely.",
    )
    parser.add_argument(
        "--cta-action",
        metavar="ACTION",
        help=(
            "CTA button action type. "
            "One of: BOOK, ORDER, SHOP, LEARN_MORE, SIGN_UP, GET_OFFER, CALL. "
            "Usually supplied together with --cta-url."
        ),
    )
    parser.add_argument(
        "--cta-url",
        metavar="URL",
        help="New destination URL for the CTA button.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print what would be changed without making any API calls. "
            "Useful for previewing an edit before committing it."
        ),
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Validate post name format before touching credentials.
    try:
        _validate_post_name(args.post_name)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Validate CTA action if supplied.
    if args.cta_action:
        try:
            _validate_cta_action(args.cta_action)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    # Must supply at least one field to update.
    if args.summary is None and args.cta_action is None and args.cta_url is None:
        print(
            "Error: Supply at least one of --summary or --cta-url.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.dry_run:
        print("[DRY RUN] Would update post:")
        print(
            _format_update_preview(
                args.post_name, args.summary, args.cta_action, args.cta_url
            )
        )
        sys.exit(0)

    # Authenticate.
    try:
        creds = get_credentials()
    except Exception as exc:
        print(f"Authentication failed: {exc}", file=sys.stderr)
        sys.exit(1)

    gbp = BusinessProfileClient(creds)

    try:
        result = run_update_post(
            args.post_name,
            gbp,
            summary=args.summary,
            cta_action=args.cta_action,
            cta_url=args.cta_url,
            dry_run=False,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Failed to update post: {exc}", file=sys.stderr)
        sys.exit(1)

    print("Updated post:")
    print(_format_result(result.get("post", {})))


if __name__ == "__main__":  # pragma: no cover
    main()

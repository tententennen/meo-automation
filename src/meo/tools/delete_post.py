"""meo-delete-post — delete a specific GBP local post by resource name.

Use meo-live-posts first to see what posts are currently live and find their
resource names (each post's "name" field), then pass that name here.

Safety:
  - Use --dry-run to confirm the post name is valid without deleting anything.
  - Supply --yes / -y to delete without an interactive confirmation prompt.
  - Without --yes the tool fetches the post, prints a summary preview, and
    asks for confirmation.  In non-interactive environments (CI, scheduled
    runs) you MUST supply --yes or --dry-run.

State note: deletion does NOT update state.json.  If the deleted post was
recorded in the local archive, it will still appear there (as "archived /
no longer live") the next time meo-live-posts reconciles.

Requirements:
  - GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN

Usage:
    # Preview without deleting
    meo-delete-post --post-name accounts/123/locations/456/localPosts/789 --dry-run

    # Delete after interactive confirmation
    meo-delete-post --post-name accounts/123/locations/456/localPosts/789

    # Delete without confirmation (CI / scripted use)
    meo-delete-post --post-name accounts/123/locations/456/localPosts/789 --yes

    python -m meo.tools.delete_post
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

# Minimum string that every valid GBP localPost resource name must contain.
_POST_NAME_MARKER = "/localPosts/"


def _validate_post_name(post_name: str) -> None:
    """Raise ValueError if post_name doesn't look like a GBP localPost resource name.

    Valid form: accounts/<account_id>/locations/<location_id>/localPosts/<post_id>
    """
    if not post_name or _POST_NAME_MARKER not in post_name:
        raise ValueError(
            f"Post name must contain '{_POST_NAME_MARKER}' "
            f"(e.g. 'accounts/123/locations/456/localPosts/789'). "
            f"Got: {post_name!r}. Run meo-live-posts to find valid post names."
        )


def _parse_create_time(create_time: str) -> str:
    """Convert a GBP ISO-8601 timestamp to a compact JST string."""
    try:
        dt = datetime.fromisoformat(create_time.replace("Z", "+00:00"))
        return dt.astimezone(_JST).strftime("%Y-%m-%d %H:%M JST")
    except Exception:
        return create_time


def _format_post_preview(post: dict[str, Any]) -> str:
    """Return a one-block human-readable preview of a local post."""
    lines: list[str] = []
    lines.append(f"  Name:    {post.get('name', '?')}")

    topic = post.get("topicType", "?")
    state = post.get("state", "?")
    lines.append(f"  Type:    {topic}   State: {state}")

    create_time = post.get("createTime", "")
    if create_time:
        lines.append(f"  Created: {_parse_create_time(create_time)}")

    summary = post.get("summary", "")
    if summary:
        preview = summary.replace("\n", " ")[:120]
        ellipsis = "…" if len(summary) > 120 else ""
        lines.append(f"  Text:    {preview}{ellipsis}")

    return "\n".join(lines)


def run_delete_post(
    post_name: str,
    gbp: BusinessProfileClient,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Delete a specific GBP local post.

    Args:
        post_name: Full GBP localPost resource name.
        gbp:       Authenticated BusinessProfileClient.
        dry_run:   If True, log intent but make no API call.

    Returns:
        Dict with keys: post_name, status ('deleted' | 'dry_run').

    Raises:
        ValueError:               if post_name is not a valid resource name.
        requests.HTTPError:       if the GBP API returns an error.
    """
    _validate_post_name(post_name)

    if dry_run:
        logger.info("DRY RUN — would delete post: %s", post_name)
        return {"post_name": post_name, "status": "dry_run"}

    gbp.delete_local_post(post_name)
    logger.info("Deleted GBP post: %s", post_name)
    return {"post_name": post_name, "status": "deleted"}


def _prompt_confirm(prompt: str = "Delete this post? [y/N] ") -> bool:
    """Return True if the user types 'y' or 'yes' (case-insensitive).

    Raises EOFError if stdin is closed (non-interactive environment).
    """
    answer = input(prompt).strip().lower()
    return answer in ("y", "yes")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Delete a specific GBP local post by its resource name.\n"
            "Run meo-live-posts first to see live post names.\n"
            "This action is irreversible — the post is removed immediately."
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
        "--dry-run",
        action="store_true",
        help="Validate the post name and log the intent — makes no API calls.",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip interactive confirmation prompt (required in non-interactive environments).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Validate post name format before touching credentials.
    try:
        _validate_post_name(args.post_name)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print(f"[DRY RUN] Would delete post: {args.post_name}")
        sys.exit(0)

    # Authenticate.
    try:
        creds = get_credentials()
    except Exception as exc:
        print(f"Authentication failed: {exc}", file=sys.stderr)
        sys.exit(1)

    gbp = BusinessProfileClient(creds)

    if not args.yes:
        # Fetch the post to show a preview before asking for confirmation.
        try:
            post = gbp.get_local_post(args.post_name)
            print("Post to be deleted:")
            print(_format_post_preview(post))
        except Exception as exc:
            logger.debug("Could not fetch post preview: %s", exc)
            print(f"Post: {args.post_name}")

        try:
            confirmed = _prompt_confirm()
        except EOFError:
            print(
                "Error: stdin is not interactive. "
                "Pass --yes to delete without a confirmation prompt.",
                file=sys.stderr,
            )
            sys.exit(1)

        if not confirmed:
            print("Cancelled — no post was deleted.")
            sys.exit(0)

    try:
        result = run_delete_post(args.post_name, gbp, dry_run=False)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Failed to delete post: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Deleted post: {result['post_name']}")


if __name__ == "__main__":  # pragma: no cover
    main()

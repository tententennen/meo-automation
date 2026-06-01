"""Optional run-completion notifications via Slack webhook.

Set SLACK_WEBHOOK_URL in your environment to receive a Slack message after each
daily run summarising what was posted and any errors.  If the variable is not
set, every function in this module is a no-op — no import error, no noise.

Ref: https://api.slack.com/messaging/webhooks
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)


def send_run_summary(results: list[dict[str, Any]], *, dry_run: bool = False) -> None:
    """Post a Slack summary of the completed run.

    Silently no-ops when SLACK_WEBHOOK_URL is not set.
    Any network or HTTP error is logged as a warning — notification failures
    never propagate and never affect the run's exit code.

    Args:
        results:  List of per-store result dicts assembled in main.py.
        dry_run:  Whether this was a dry run (changes the message header).
    """
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return

    text = _format_message(results, dry_run=dry_run)
    try:
        resp = requests.post(webhook_url, json={"text": text}, timeout=10)
        resp.raise_for_status()
        logger.debug("Slack notification sent.")
    except Exception as exc:
        logger.warning("Slack notification failed (non-fatal): %s", exc)


def _format_message(results: list[dict[str, Any]], *, dry_run: bool) -> str:
    """Build the Slack message text from per-store results."""
    mode = "DRY RUN" if dry_run else "LIVE"
    lines: list[str] = [f"*MEO Automation — {mode} run complete*"]

    had_error = False
    for r in results:
        store_key = r.get("store_key", "?")

        if r.get("error"):
            had_error = True
            lines.append(f"• *{store_key}*: ❌ {r['error']}")
            continue

        parts: list[str] = []

        post = r.get("post", {})
        if post:
            status = post.get("status", post.get("error", "—"))
            theme = post.get("theme", "")
            post_part = f"post: {status}"
            if theme:
                post_part += f" ({theme})"
            parts.append(post_part)

        reviews = r.get("reviews", {})
        if reviews:
            replied = reviews.get("replied", 0)
            deferred = reviews.get("deferred", 0)
            rev_errors = reviews.get("errors", [])
            rev_part = f"replies: {replied}"
            if deferred:
                rev_part += f", {deferred} deferred"
            if rev_errors:
                rev_part += f", {len(rev_errors)} error(s)"
                had_error = True
            parts.append(rev_part)

        detail = " | ".join(parts) if parts else "no actions"
        lines.append(f"• *{store_key}*: {detail}")

    footer = "⚠️ Some errors occurred — check the Actions log." if had_error else "✅ All stores processed."
    lines.append(footer)
    return "\n".join(lines)

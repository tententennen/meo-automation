"""Shared constants, URL templates, and helpers for the GBP API client modules.

Internal module — not part of the public meo API.
"""

from __future__ import annotations

import requests

_LOCAL_POSTS_BASE = "https://mybusiness.googleapis.com/v4/{location}/localPosts"
_REVIEWS_BASE = "https://mybusiness.googleapis.com/v4/{location}/reviews"
_REVIEW_REPLY_BASE = (
    "https://mybusiness.googleapis.com/v4/{location}/reviews/{review_id}/reply"
)
# Media upload endpoint — multipart upload returns a Media resource with googleUrl.
# Ref: https://developers.google.com/my-business/reference/rest/v4/accounts.locations.media/create
_MEDIA_UPLOAD_BASE = "https://mybusiness.googleapis.com/upload/v4/{location}/media"
# Q&A (Questions & Answers) API — separate host from the mybusiness API.
# Ref: https://developers.google.com/my-business/reference/qanda/rest/v1/locations.questions
_QA_BASE = "https://mybusinessqanda.googleapis.com/v1"

_DEFAULT_TIMEOUT = (10, 60)  # (connect_seconds, read_seconds)


def _qa_location_name(location_id: str) -> str:
    """Extract the 'locations/{id}' segment from a full GBP location resource name.

    The mybusinessqanda API takes 'locations/{locationId}' as the parent,
    without the 'accounts/{accountId}/' prefix used by the mybusiness API.

    >>> _qa_location_name("accounts/123/locations/456")
    'locations/456'
    >>> _qa_location_name("locations/456")
    'locations/456'
    """
    parts = location_id.split("/")
    try:
        idx = parts.index("locations")
        return "/".join(parts[idx : idx + 2])
    except ValueError:
        return location_id


def _raise_for_status(resp: requests.Response) -> None:
    """Call raise_for_status() with the API error body included in the message.

    requests.raise_for_status() only shows the HTTP status line; the GBP API
    always returns a JSON body with a human-readable 'message' field.  Including
    it makes error logs and Slack notifications directly actionable without
    needing to inspect raw responses.

    For 403 specifically, appends a hint about Business Profile API access,
    because PERMISSION_DENIED is the most common first-run error (API not yet
    approved or OAuth scopes not granted).
    """
    if resp.ok:
        return
    try:
        detail = resp.json().get("error", {}).get("message", "")
    except Exception:
        detail = resp.text[:200] if resp.text else ""

    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        msg = str(exc)
        if detail:
            msg = f"{msg} — API error: {detail}"
        if resp.status_code == 403:
            msg = (
                f"{msg}\n"
                "Hint: If you have not yet requested Business Profile API access, "
                "visit https://developers.google.com/my-business/content/prereqs"
            )
        raise requests.HTTPError(msg, response=resp) from exc

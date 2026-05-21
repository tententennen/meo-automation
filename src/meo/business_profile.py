"""Google Business Profile API client wrapper.

Relevant API reference:
  https://developers.google.com/my-business/reference/businessinformation/rest
  https://developers.google.com/my-business/reference/rest  (local posts, reviews)

Note: The GBP API uses a non-discovery-based endpoint for some resources.
We hit the REST URLs directly via the authorized session from google-auth.

Endpoint base URLs (as of 2024):
  Local posts:  https://mybusiness.googleapis.com/v4/{location}/localPosts
  Reviews:      https://mybusiness.googleapis.com/v4/{location}/reviews

TODO: confirm exact v4 vs v1 versioning when the API approval is granted.
      See: https://developers.google.com/my-business/reference/rest/v4/accounts.locations.localPosts
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)

_LOCAL_POSTS_BASE = "https://mybusiness.googleapis.com/v4/{location}/localPosts"
_REVIEWS_BASE = "https://mybusiness.googleapis.com/v4/{location}/reviews"
_REVIEW_REPLY_BASE = (
    "https://mybusiness.googleapis.com/v4/{location}/reviews/{review_id}/reply"
)


class BusinessProfileClient:
    """Thin wrapper around the GBP REST API using an authorized requests session."""

    def __init__(self, credentials: Credentials) -> None:
        self._creds = credentials
        self._session = _AuthSession(credentials)

    # ------------------------------------------------------------------
    # Local Posts
    # ------------------------------------------------------------------

    def create_local_post(
        self,
        location_id: str,
        summary: str,
        media_url: str | None = None,
        *,
        call_to_action: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a 最新情報 local post on the given location.

        Args:
            location_id: Full resource name, e.g. "accounts/123/locations/456".
            summary:     Post body text (Japanese, ≤1500 chars).
            media_url:   Publicly accessible image URL to attach (optional).
            call_to_action: Optional dict with keys 'actionType' and 'url'.

        Returns:
            The created LocalPost resource dict.

        TODO: GBP API requires the image to be uploaded via the media endpoint
              before referencing it in a post. Wire up _upload_media() below
              once API access is approved and endpoint shape is confirmed.
              Ref: https://developers.google.com/my-business/reference/rest/v4/accounts.locations.media
        """
        url = _LOCAL_POSTS_BASE.format(location=location_id)
        body: dict[str, Any] = {
            "languageCode": "ja",
            "summary": summary,
            "topicType": "STANDARD",
        }
        if call_to_action:
            body["callToAction"] = call_to_action
        if media_url:
            body["media"] = [{"mediaFormat": "PHOTO", "sourceUrl": media_url}]

        resp = self._session.post(url, json=body)
        resp.raise_for_status()
        result = resp.json()
        logger.info("Created local post: %s", result.get("name"))
        return result

    # ------------------------------------------------------------------
    # Reviews
    # ------------------------------------------------------------------

    def list_reviews(
        self, location_id: str, page_size: int = 50
    ) -> list[dict[str, Any]]:
        """Return all reviews for a location (handles pagination automatically).

        Ref: https://developers.google.com/my-business/reference/rest/v4/accounts.locations.reviews/list
        """
        url = _REVIEWS_BASE.format(location=location_id)
        reviews: list[dict[str, Any]] = []
        params: dict[str, Any] = {"pageSize": page_size}

        while True:
            resp = self._session.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            reviews.extend(data.get("reviews", []))
            next_token = data.get("nextPageToken")
            if not next_token:
                break
            params["pageToken"] = next_token

        logger.info("Fetched %d reviews for %s", len(reviews), location_id)
        return reviews

    def reply_to_review(
        self, location_id: str, review_id: str, reply_text: str
    ) -> dict[str, Any]:
        """Post or update a reply to a review.

        Ref: https://developers.google.com/my-business/reference/rest/v4/accounts.locations.reviews/updateReply
        """
        url = _REVIEW_REPLY_BASE.format(
            location=location_id, review_id=review_id
        )
        body = {"comment": reply_text}
        resp = self._session.put(url, json=body)
        resp.raise_for_status()
        result = resp.json()
        logger.info("Replied to review %s on %s", review_id, location_id)
        return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class _AuthSession:
    """A thin requests wrapper that injects a fresh Bearer token on each call."""

    def __init__(self, credentials: Credentials) -> None:
        self._creds = credentials
        self._session = requests.Session()

    def _refresh_if_needed(self) -> None:
        if not self._creds.valid:
            from google.auth.transport.requests import Request
            self._creds.refresh(Request())

    def _headers(self) -> dict[str, str]:
        self._refresh_if_needed()
        return {"Authorization": f"Bearer {self._creds.token}"}

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self._session.get(url, headers=self._headers(), **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        return self._session.post(url, headers=self._headers(), **kwargs)

    def put(self, url: str, **kwargs: Any) -> requests.Response:
        return self._session.put(url, headers=self._headers(), **kwargs)

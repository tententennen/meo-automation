"""Google Business Profile API client wrapper.

Relevant API reference:
  https://developers.google.com/my-business/reference/businessinformation/rest
  https://developers.google.com/my-business/reference/rest  (local posts, reviews)

Note: The GBP API uses a non-discovery-based endpoint for some resources.
We hit the REST URLs directly via the authorized session from google-auth.

Endpoint base URLs (as of 2024):
  Local posts:  https://mybusiness.googleapis.com/v4/{location}/localPosts
  Reviews:      https://mybusiness.googleapis.com/v4/{location}/reviews
  Media upload: https://mybusiness.googleapis.com/upload/v4/{location}/media

TODO: confirm exact v4 vs v1 versioning when the API approval is granted.
      See: https://developers.google.com/my-business/reference/rest/v4/accounts.locations.localPosts
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)

_LOCAL_POSTS_BASE = "https://mybusiness.googleapis.com/v4/{location}/localPosts"
_REVIEWS_BASE = "https://mybusiness.googleapis.com/v4/{location}/reviews"
_REVIEW_REPLY_BASE = (
    "https://mybusiness.googleapis.com/v4/{location}/reviews/{review_id}/reply"
)
# Media upload endpoint — multipart upload returns a Media resource with googleUrl.
# Ref: https://developers.google.com/my-business/reference/rest/v4/accounts.locations.media/create
_MEDIA_UPLOAD_BASE = "https://mybusiness.googleapis.com/upload/v4/{location}/media"


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
                         Prefer a URL returned by upload_media_bytes() over a raw
                         Drive webContentLink (Drive links require auth).
            call_to_action: Optional dict with keys 'actionType' and 'url'.

        Returns:
            The created LocalPost resource dict.
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

    def upload_media_bytes(
        self,
        location_id: str,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> str:
        """Upload image bytes to GBP and return the hosted googleUrl.

        The returned URL can be passed directly as media_url to create_local_post().
        This is the correct approach for images stored in private Drive folders —
        download via Drive API (authenticated), then upload to GBP here.

        Args:
            location_id: Full resource name, e.g. "accounts/123/locations/456".
            image_bytes: Raw image data (JPEG, PNG, or WebP).
            mime_type:   MIME type of the image bytes (default: image/jpeg).

        Returns:
            The googleUrl string from the created GBP Media resource.

        TODO: Confirm response field name (googleUrl vs sourceUrl) once API access
              is granted and a real upload can be tested.
              Ref: https://developers.google.com/my-business/reference/rest/v4/accounts.locations.media#Media
        """
        url = _MEDIA_UPLOAD_BASE.format(location=location_id)
        boundary = "meo_upload_boundary_v1"
        metadata = b'{"mediaFormat": "PHOTO"}'

        parts: list[bytes] = [
            b"--" + boundary.encode(),
            b"Content-Type: application/json; charset=UTF-8",
            b"",
            metadata,
            b"--" + boundary.encode(),
            b"Content-Type: " + mime_type.encode(),
            b"",
            image_bytes,
            b"--" + boundary.encode() + b"--",
        ]
        body = b"\r\n".join(parts)

        resp = self._session.post(
            url,
            params={"uploadType": "multipart"},
            data=body,
            headers={"Content-Type": f"multipart/related; boundary={boundary}"},
        )
        resp.raise_for_status()
        result = resp.json()
        # GBP returns googleUrl for hosted images; fall back to sourceUrl if absent.
        google_url = result.get("googleUrl") or result.get("sourceUrl")
        if not google_url:
            raise RuntimeError(
                f"GBP media upload succeeded but returned no URL. Response: {result}"
            )
        logger.info("Uploaded media to GBP for %s: %s", location_id, google_url)
        return google_url

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

_DEFAULT_TIMEOUT = (10, 60)  # (connect_seconds, read_seconds)


class _AuthSession:
    """A thin requests wrapper that injects a fresh Bearer token on each call.

    GET and PUT requests are automatically retried (up to 3 times with backoff)
    on transient failures (429, 5xx).  GET is safe to retry by definition; PUT
    is idempotent so retrying a failed reply_to_review never creates duplicates.
    POST is NOT retried — create_local_post is not idempotent and retrying would
    publish duplicate posts.

    All requests carry a (connect=10s, read=60s) timeout so the tool never
    hangs indefinitely on a stalled network connection.
    """

    def __init__(self, credentials: Credentials) -> None:
        self._creds = credentials
        self._session = requests.Session()
        # Retry GET (safe) and PUT (idempotent) on transient failures.
        # POST is excluded — retrying create_local_post would publish duplicate posts.
        _retry = Retry(
            total=3,
            backoff_factor=1.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "PUT"],
            raise_on_status=False,
        )
        self._session.mount("https://", HTTPAdapter(max_retries=_retry))

    def _refresh_if_needed(self) -> None:
        if not self._creds.valid:
            from google.auth.transport.requests import Request
            self._creds.refresh(Request())

    def _auth_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        """Return auth headers merged with any caller-supplied extra headers."""
        self._refresh_if_needed()
        headers = {"Authorization": f"Bearer {self._creds.token}"}
        if extra:
            headers.update(extra)
        return headers

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        extra = kwargs.pop("headers", None)
        kwargs.setdefault("timeout", _DEFAULT_TIMEOUT)
        return self._session.get(url, headers=self._auth_headers(extra), **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        extra = kwargs.pop("headers", None)
        kwargs.setdefault("timeout", _DEFAULT_TIMEOUT)
        return self._session.post(url, headers=self._auth_headers(extra), **kwargs)

    def put(self, url: str, **kwargs: Any) -> requests.Response:
        extra = kwargs.pop("headers", None)
        kwargs.setdefault("timeout", _DEFAULT_TIMEOUT)
        return self._session.put(url, headers=self._auth_headers(extra), **kwargs)

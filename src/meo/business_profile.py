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

from google.oauth2.credentials import Credentials

from ._bp_constants import (
    _LOCAL_POSTS_BASE,
    _MEDIA_UPLOAD_BASE,
    _QA_BASE,
    _REVIEW_REPLY_BASE,
    _REVIEWS_BASE,
    _qa_location_name,
    _raise_for_status,
)
from ._bp_auth_session import _AuthSession, _DEFAULT_TIMEOUT  # noqa: F401 — re-exported for tests
from ._bp_post_types import _PostTypesMixin
from ._bp_qa import _QaMixin

logger = logging.getLogger(__name__)


class BusinessProfileClient(_QaMixin, _PostTypesMixin):
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
        _raise_for_status(resp)
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
        _raise_for_status(resp)
        result = resp.json()
        # GBP returns googleUrl for hosted images; fall back to sourceUrl if absent.
        google_url = result.get("googleUrl") or result.get("sourceUrl")
        if not google_url:
            raise RuntimeError(
                f"GBP media upload succeeded but returned no URL. Response: {result}"
            )
        logger.info("Uploaded media to GBP for %s: %s", location_id, google_url)
        return google_url

    def get_local_post(self, post_name: str) -> dict[str, Any]:
        """Fetch a single local post by its full resource name.

        Args:
            post_name: Full resource name, e.g.
                       "accounts/123/locations/456/localPosts/789".

        Returns:
            The LocalPost resource dict (fields: name, summary, state,
            createTime, updateTime, topicType, …).

        Raises:
            requests.HTTPError: 404 if the post does not exist or has expired.

        Ref: https://developers.google.com/my-business/reference/rest/v4/accounts.locations.localPosts/get
        """
        url = f"https://mybusiness.googleapis.com/v4/{post_name}"
        resp = self._session.get(url)
        _raise_for_status(resp)
        return resp.json()

    def delete_local_post(self, post_name: str) -> None:
        """Delete a local post by its full resource name.

        Once deleted, the post is immediately removed from the GBP listing.
        This action is irreversible — there is no trash / undo in the GBP API.

        Args:
            post_name: Full resource name, e.g.
                       "accounts/123/locations/456/localPosts/789".
                       Obtain names via list_local_posts() or meo-live-posts.

        Raises:
            requests.HTTPError: If the API returns an error (e.g. 404 post
                not found / already deleted, 403 insufficient permissions).

        Ref: https://developers.google.com/my-business/reference/rest/v4/accounts.locations.localPosts/delete
        """
        url = f"https://mybusiness.googleapis.com/v4/{post_name}"
        resp = self._session.delete(url)
        _raise_for_status(resp)
        logger.info("Deleted local post: %s", post_name)

    def update_local_post(
        self,
        post_name: str,
        *,
        summary: str | None = None,
        cta_action: str | None = None,
        cta_url: str | None = None,
    ) -> dict[str, Any]:
        """Patch a live local post's text and/or call-to-action.

        Only the fields named in ``updateMask`` are changed; omitted fields
        are left untouched.  At least one of ``summary`` or ``cta_url``
        (or ``cta_action``) must be supplied.

        Args:
            post_name:  Full resource name, e.g.
                        "accounts/123/locations/456/localPosts/789".
            summary:    New post body text (replaces the existing summary).
            cta_action: CTA button type: BOOK, ORDER, SHOP, LEARN_MORE,
                        SIGN_UP, GET_OFFER, CALL.  Must be supplied together
                        with cta_url unless the post already has a CTA.
            cta_url:    New destination URL for the CTA button.

        Returns:
            The updated LocalPost resource as returned by the API.

        Raises:
            ValueError:          If no fields to update are supplied.
            requests.HTTPError:  On API error (404, 403, 400, …).

        Ref: https://developers.google.com/my-business/reference/rest/v4/accounts.locations.localPosts/patch
        """
        body: dict[str, Any] = {}
        mask_fields: list[str] = []

        if summary is not None:
            body["summary"] = summary
            mask_fields.append("summary")

        if cta_action is not None or cta_url is not None:
            cta: dict[str, Any] = {}
            if cta_action is not None:
                cta["actionType"] = cta_action
            if cta_url is not None:
                cta["url"] = cta_url
            body["callToAction"] = cta
            mask_fields.append("callToAction")

        if not mask_fields:
            raise ValueError(
                "At least one field must be updated: supply --summary and/or --cta-url."
            )

        url = f"https://mybusiness.googleapis.com/v4/{post_name}"
        params = {"updateMask": ",".join(mask_fields)}
        resp = self._session.patch(url, params=params, json=body)
        _raise_for_status(resp)
        updated = resp.json()
        logger.info(
            "Updated local post %s (mask: %s)", post_name, ",".join(mask_fields)
        )
        return updated

    def list_local_posts(
        self, location_id: str, page_size: int = 20
    ) -> list[dict[str, Any]]:
        """Return all local posts for a location (handles pagination automatically).

        Ref: https://developers.google.com/my-business/reference/rest/v4/accounts.locations.localPosts/list

        Each item contains at minimum:
          name, summary, state, createTime, updateTime, topicType
        State values: LIVE, REJECTED, PROCESSING, UNKNOWN_STATE

        Note: STANDARD (最新情報) posts expire after 6 months; only active posts
        are returned, so the list shrinks over time as old posts expire.
        """
        url = _LOCAL_POSTS_BASE.format(location=location_id)
        posts: list[dict[str, Any]] = []
        params: dict[str, Any] = {"pageSize": page_size}

        while True:
            resp = self._session.get(url, params=params)
            _raise_for_status(resp)
            data = resp.json()
            posts.extend(data.get("localPosts", []))
            next_token = data.get("nextPageToken")
            if not next_token:
                break
            params["pageToken"] = next_token

        logger.info("Fetched %d local posts for %s", len(posts), location_id)
        return posts

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
            _raise_for_status(resp)
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
        _raise_for_status(resp)
        result = resp.json()
        logger.info("Replied to review %s on %s", review_id, location_id)
        return result

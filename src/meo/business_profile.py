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
# Q&A (Questions & Answers) API — separate host from the mybusiness API.
# Ref: https://developers.google.com/my-business/reference/qanda/rest/v1/locations.questions
_QA_BASE = "https://mybusinessqanda.googleapis.com/v1"


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

    def create_offer_post(
        self,
        location_id: str,
        title: str,
        summary: str,
        *,
        start_date: dict[str, int] | None = None,
        end_date: dict[str, int] | None = None,
        coupon_code: str | None = None,
        redeem_url: str | None = None,
        terms: str | None = None,
        media_url: str | None = None,
        call_to_action: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create an OFFER-type local post (時限キャンペーン) on the given location.

        OFFER posts include a title, date range, optional coupon code, redemption
        URL, and terms & conditions.  They appear in a distinct OFFER slot on the
        GBP listing.

        Args:
            location_id: Full resource name, e.g. "accounts/123/locations/456".
            title:       Offer title displayed prominently (e.g. "夏の特別キャンペーン").
            summary:     Post body text (Japanese, ≤1500 chars).
            start_date:  Offer start date as {"year": int, "month": int, "day": int}.
            end_date:    Offer end date as {"year": int, "month": int, "day": int}.
            coupon_code: Optional coupon / promo code string.
            redeem_url:  Optional URL where customers can redeem the offer online.
            terms:       Optional terms & conditions text.
            media_url:   Publicly accessible image URL to attach (optional).
            call_to_action: Optional dict with keys 'actionType' and 'url'.

        Returns:
            The created LocalPost resource dict.

        Ref: https://developers.google.com/my-business/reference/rest/v4/accounts.locations.localPosts
        """
        url = _LOCAL_POSTS_BASE.format(location=location_id)
        body: dict[str, Any] = {
            "languageCode": "ja",
            "summary": summary,
            "topicType": "OFFER",
        }

        # Event block carries title + optional date range.
        event: dict[str, Any] = {"title": title}
        if start_date or end_date:
            schedule: dict[str, Any] = {}
            if start_date:
                schedule["startDate"] = start_date
            if end_date:
                schedule["endDate"] = end_date
            event["schedule"] = schedule
        body["event"] = event

        # Offer block carries coupon, redemption URL, and terms.
        offer: dict[str, Any] = {}
        if coupon_code:
            offer["couponCode"] = coupon_code
        if redeem_url:
            offer["redeemOnlineUrl"] = redeem_url
        if terms:
            offer["termsConditions"] = terms
        if offer:
            body["offer"] = offer

        if call_to_action:
            body["callToAction"] = call_to_action
        if media_url:
            body["media"] = [{"mediaFormat": "PHOTO", "sourceUrl": media_url}]

        resp = self._session.post(url, json=body)
        _raise_for_status(resp)
        result = resp.json()
        logger.info("Created offer post: %s", result.get("name"))
        return result

    def create_event_post(
        self,
        location_id: str,
        title: str,
        summary: str,
        *,
        start_date: dict[str, int] | None = None,
        end_date: dict[str, int] | None = None,
        start_time: dict[str, int] | None = None,
        end_time: dict[str, int] | None = None,
        media_url: str | None = None,
        call_to_action: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create an EVENT-type local post (イベント) on the given location.

        EVENT posts include a title, optional date+time range, and appear on
        the GBP listing as an event card.  Use for workshops, special classes,
        anniversary celebrations, guest instructor sessions, etc.

        Args:
            location_id: Full resource name, e.g. "accounts/123/locations/456".
            title:       Event name (e.g. "特別ヨガクラス").
            summary:     Post body text (Japanese, ≤1500 chars).
            start_date:  Event start date as {"year": int, "month": int, "day": int}.
            end_date:    Event end date as {"year": int, "month": int, "day": int}.
            start_time:  Event start time as {"hours": int, "minutes": int} (optional).
            end_time:    Event end time as {"hours": int, "minutes": int} (optional).
            media_url:   Publicly accessible image URL to attach (optional).
            call_to_action: Optional dict with keys 'actionType' and 'url'.

        Returns:
            The created LocalPost resource dict.

        Ref: https://developers.google.com/my-business/reference/rest/v4/accounts.locations.localPosts
        """
        url = _LOCAL_POSTS_BASE.format(location=location_id)
        body: dict[str, Any] = {
            "languageCode": "ja",
            "summary": summary,
            "topicType": "EVENT",
        }

        # Event block: title + optional date/time range.
        event: dict[str, Any] = {"title": title}
        if start_date or end_date or start_time or end_time:
            schedule: dict[str, Any] = {}
            if start_date:
                schedule["startDate"] = start_date
            if end_date:
                schedule["endDate"] = end_date
            if start_time:
                schedule["startTime"] = start_time
            if end_time:
                schedule["endTime"] = end_time
            event["schedule"] = schedule
        body["event"] = event

        if call_to_action:
            body["callToAction"] = call_to_action
        if media_url:
            body["media"] = [{"mediaFormat": "PHOTO", "sourceUrl": media_url}]

        resp = self._session.post(url, json=body)
        _raise_for_status(resp)
        result = resp.json()
        logger.info("Created event post: %s", result.get("name"))
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

    # -----------------------------------------------------------------------
    # Q&A (Questions & Answers)
    # Ref: https://developers.google.com/my-business/reference/qanda/rest/v1/locations.questions
    # -----------------------------------------------------------------------

    def list_questions(
        self,
        location_id: str,
        *,
        page_size: int = 20,
        answers_per_question: int = 5,
    ) -> list[dict[str, Any]]:
        """Fetch all Q&A questions for a location, paginating automatically.

        Returns a flat list of question dicts, each including the topAnswers
        sub-list so callers can detect whether the owner has already replied.

        Args:
            location_id:          Full location resource name, e.g.
                                  'accounts/{a}/locations/{l}'.
            page_size:            Max questions per API page (API max: 100).
            answers_per_question: Top answers to include per question (max: 10).

        Ref: https://developers.google.com/my-business/reference/qanda/rest/v1/locations.questions/list
        """
        qa_parent = _qa_location_name(location_id)
        url = f"{_QA_BASE}/{qa_parent}/questions"
        params: dict[str, Any] = {
            "pageSize": page_size,
            "answersPerQuestion": answers_per_question,
        }
        questions: list[dict[str, Any]] = []

        while True:
            resp = self._session.get(url, params=params)
            _raise_for_status(resp)
            data = resp.json()
            questions.extend(data.get("questions", []))
            next_token = data.get("nextPageToken")
            if not next_token:
                break
            params["pageToken"] = next_token

        logger.info("Fetched %d Q&A questions for %s.", len(questions), location_id)
        return questions

    def upsert_answer(self, question_name: str, answer_text: str) -> dict[str, Any]:
        """Post or update the owner's answer to a Q&A question.

        Creates a new answer if none exists; replaces the owner's existing
        answer if one was already posted.

        Args:
            question_name: Full question resource name.
                           Format: 'locations/{locationId}/questions/{questionId}'
            answer_text:   The answer text to post.

        Returns:
            The Answer resource dict returned by the API.

        Ref: https://developers.google.com/my-business/reference/qanda/rest/v1/locations.questions.answers/upsert
        """
        url = f"{_QA_BASE}/{question_name}:upsertAnswer"
        body = {"answer": {"text": answer_text}}
        resp = self._session.post(url, json=body)
        _raise_for_status(resp)
        result = resp.json()
        logger.info("Posted answer for question %s.", question_name)
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

    def patch(self, url: str, **kwargs: Any) -> requests.Response:
        extra = kwargs.pop("headers", None)
        kwargs.setdefault("timeout", _DEFAULT_TIMEOUT)
        return self._session.patch(url, headers=self._auth_headers(extra), **kwargs)

    def delete(self, url: str, **kwargs: Any) -> requests.Response:
        extra = kwargs.pop("headers", None)
        kwargs.setdefault("timeout", _DEFAULT_TIMEOUT)
        return self._session.delete(url, headers=self._auth_headers(extra), **kwargs)

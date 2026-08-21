"""Mixin: OFFER and EVENT typed local post creation methods for BusinessProfileClient.

Internal module — not part of the public meo API.
"""

from __future__ import annotations

import logging
from typing import Any

from ._bp_constants import _LOCAL_POSTS_BASE, _raise_for_status

logger = logging.getLogger(__name__)


class _PostTypesMixin:
    """Provides create_offer_post() and create_event_post() to BusinessProfileClient."""

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

        resp = self._session.post(url, json=body)  # type: ignore[attr-defined]
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

        resp = self._session.post(url, json=body)  # type: ignore[attr-defined]
        _raise_for_status(resp)
        result = resp.json()
        logger.info("Created event post: %s", result.get("name"))
        return result

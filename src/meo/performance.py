"""Google Business Profile Performance API client.

Fetches daily performance metrics (search impressions, map views, clicks)
for a Business Profile location.

Endpoint:
  GET https://businessprofileperformance.googleapis.com/v1/{name}:fetchMultiDailyMetricsTimeSeries

Scope: https://www.googleapis.com/auth/business.manage
  (same OAuth scope as the main GBP API — no additional credentials needed)

Name format for this API (v1 Performance API):
  The Performance API uses 'locations/{location_id}' — NOT the full v4 account
  path ('accounts/{a}/locations/{id}').  Use _performance_name() to convert.

Available metrics:
  BUSINESS_IMPRESSIONS_DESKTOP_MAPS    — times shown on Google Maps (desktop)
  BUSINESS_IMPRESSIONS_DESKTOP_SEARCH  — times shown in Google Search (desktop)
  BUSINESS_IMPRESSIONS_MOBILE_MAPS     — times shown on Google Maps (mobile)
  BUSINESS_IMPRESSIONS_MOBILE_SEARCH   — times shown in Google Search (mobile)
  BUSINESS_DIRECTION_REQUESTS          — direction requests from Maps
  CALL_CLICKS                          — calls initiated from the profile
  WEBSITE_CLICKS                       — clicks to the website link

Ref: https://developers.google.com/my-business/reference/businessprofileperformance/rest/v1/locations/fetchMultiDailyMetricsTimeSeries
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from google.oauth2.credentials import Credentials

from .business_profile import _AuthSession, _raise_for_status

logger = logging.getLogger(__name__)

_PERF_BASE = "https://businessprofileperformance.googleapis.com/v1"

METRICS_IMPRESSIONS: list[str] = [
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
    "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
    "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
]

METRICS_ACTIONS: list[str] = [
    "BUSINESS_DIRECTION_REQUESTS",
    "CALL_CLICKS",
    "WEBSITE_CLICKS",
]

ALL_METRICS: list[str] = METRICS_IMPRESSIONS + METRICS_ACTIONS


def _performance_name(location_id: str) -> str:
    """Convert a GBP location identifier to the Performance API v1 name format.

    The Performance API v1 uses 'locations/{location_id}' (just the numeric ID),
    not the full v4 account path ('accounts/{a}/locations/{id}').

    Examples:
        'accounts/123456/locations/789' → 'locations/789'
        'locations/789'                 → 'locations/789'   (no change)
        '789'                           → 'locations/789'   (bare ID)
    """
    if location_id.startswith("locations/"):
        return location_id
    idx = location_id.find("/locations/")
    if idx >= 0:
        return location_id[idx + 1:]  # keep the 'locations/{id}' suffix
    return f"locations/{location_id}"


def _parse_response(data: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Parse the fetchMultiDailyMetricsTimeSeries response.

    Returns:
        A nested dict {metric_name: {date_iso_str: count_int, ...}, ...}.
        Dates without a value (or with a null/"0" value) are included as 0.
        Malformed date entries are silently skipped.
    """
    result: dict[str, dict[str, int]] = {}
    for series in data.get("multiDailyMetricTimeSeries", []):
        metric = series.get("dailyMetric", "UNKNOWN")
        dated_values: dict[str, int] = {}
        for dv in series.get("timeSeries", {}).get("datedValues", []):
            d = dv.get("date", {})
            try:
                iso = date(d["year"], d["month"], d["day"]).isoformat()
                # API returns values as strings; absent/null → 0.
                raw_val = dv.get("value")
                value = int(raw_val) if raw_val else 0
            except (KeyError, ValueError, TypeError):
                continue
            dated_values[iso] = value
        result[metric] = dated_values
    return result


class PerformanceClient:
    """Client for the Business Profile Performance API v1."""

    def __init__(self, credentials: Credentials) -> None:
        self._session = _AuthSession(credentials)

    def fetch_daily_metrics(
        self,
        location_id: str,
        start_date: date,
        end_date: date,
        metrics: list[str] | None = None,
    ) -> dict[str, dict[str, int]]:
        """Fetch daily performance time series for a location.

        Args:
            location_id: GBP location resource name (accepts v4 or v1 format,
                         or a bare numeric ID — see _performance_name()).
            start_date:  First day of the date range (inclusive).
            end_date:    Last day of the date range (inclusive).
            metrics:     Metric names to fetch.  Defaults to ALL_METRICS.

        Returns:
            {metric_name: {date_iso: count, ...}, ...}

        Note: The API's maximum supported date range is 18 months.
              Requesting a wider range still succeeds but data is capped.

        Ref: https://developers.google.com/my-business/reference/businessprofileperformance/rest/v1/locations/fetchMultiDailyMetricsTimeSeries
        """
        if metrics is None:
            metrics = ALL_METRICS

        name = _performance_name(location_id)
        url = f"{_PERF_BASE}/{name}:fetchMultiDailyMetricsTimeSeries"

        # requests supports repeated params as a list of (key, value) tuples.
        params: list[tuple[str, Any]] = [("dailyMetric", m) for m in metrics]
        params += [
            ("dailyRange.startDate.year", start_date.year),
            ("dailyRange.startDate.month", start_date.month),
            ("dailyRange.startDate.day", start_date.day),
            ("dailyRange.endDate.year", end_date.year),
            ("dailyRange.endDate.month", end_date.month),
            ("dailyRange.endDate.day", end_date.day),
        ]

        resp = self._session.get(url, params=params)
        _raise_for_status(resp)
        data = resp.json()
        logger.info("Fetched performance metrics for %s (%s → %s)", location_id, start_date, end_date)
        return _parse_response(data)

"""Tests for meo/performance.py — _AuthSession and _raise_for_status are mocked."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
import requests

from meo.performance import (
    ALL_METRICS,
    METRICS_ACTIONS,
    METRICS_IMPRESSIONS,
    PerformanceClient,
    _parse_response,
    _performance_name,
)


# ---------------------------------------------------------------------------
# _performance_name
# ---------------------------------------------------------------------------

def test_performance_name_full_v4_path():
    assert _performance_name("accounts/123456/locations/789") == "locations/789"


def test_performance_name_already_v1():
    assert _performance_name("locations/789") == "locations/789"


def test_performance_name_bare_id():
    assert _performance_name("789") == "locations/789"


def test_performance_name_long_account_id():
    assert _performance_name("accounts/1234567890/locations/9876543210") == "locations/9876543210"


def test_performance_name_empty_string():
    # Empty string treated as bare ID — avoids crashing on unconfigured stores.
    assert _performance_name("") == "locations/"


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

_SAMPLE_RESPONSE = {
    "multiDailyMetricTimeSeries": [
        {
            "dailyMetric": "WEBSITE_CLICKS",
            "timeSeries": {
                "datedValues": [
                    {"date": {"year": 2026, "month": 8, "day": 1}, "value": "42"},
                    {"date": {"year": 2026, "month": 8, "day": 2}, "value": "38"},
                ]
            },
        },
        {
            "dailyMetric": "CALL_CLICKS",
            "timeSeries": {
                "datedValues": [
                    {"date": {"year": 2026, "month": 8, "day": 1}, "value": "5"},
                ]
            },
        },
    ]
}


def test_parse_response_basic():
    result = _parse_response(_SAMPLE_RESPONSE)
    assert result["WEBSITE_CLICKS"]["2026-08-01"] == 42
    assert result["WEBSITE_CLICKS"]["2026-08-02"] == 38
    assert result["CALL_CLICKS"]["2026-08-01"] == 5


def test_parse_response_empty_body():
    result = _parse_response({})
    assert result == {}


def test_parse_response_empty_series():
    result = _parse_response({"multiDailyMetricTimeSeries": []})
    assert result == {}


def test_parse_response_null_value():
    data = {
        "multiDailyMetricTimeSeries": [
            {
                "dailyMetric": "WEBSITE_CLICKS",
                "timeSeries": {
                    "datedValues": [
                        {"date": {"year": 2026, "month": 8, "day": 1}, "value": None},
                    ]
                },
            }
        ]
    }
    result = _parse_response(data)
    assert result["WEBSITE_CLICKS"]["2026-08-01"] == 0


def test_parse_response_missing_value_key():
    data = {
        "multiDailyMetricTimeSeries": [
            {
                "dailyMetric": "CALL_CLICKS",
                "timeSeries": {
                    "datedValues": [
                        {"date": {"year": 2026, "month": 7, "day": 31}},  # no 'value' key
                    ]
                },
            }
        ]
    }
    result = _parse_response(data)
    assert result["CALL_CLICKS"]["2026-07-31"] == 0


def test_parse_response_malformed_date_skipped():
    data = {
        "multiDailyMetricTimeSeries": [
            {
                "dailyMetric": "WEBSITE_CLICKS",
                "timeSeries": {
                    "datedValues": [
                        {"date": {"year": 2026, "month": 13, "day": 1}, "value": "10"},  # month 13
                        {"date": {"year": 2026, "month": 8, "day": 2}, "value": "5"},
                    ]
                },
            }
        ]
    }
    result = _parse_response(data)
    assert "2026-08-02" in result["WEBSITE_CLICKS"]
    assert len(result["WEBSITE_CLICKS"]) == 1  # bad entry skipped


def test_parse_response_missing_date_key_skipped():
    data = {
        "multiDailyMetricTimeSeries": [
            {
                "dailyMetric": "WEBSITE_CLICKS",
                "timeSeries": {
                    "datedValues": [
                        {"value": "10"},  # no 'date' key
                        {"date": {"year": 2026, "month": 8, "day": 3}, "value": "7"},
                    ]
                },
            }
        ]
    }
    result = _parse_response(data)
    assert list(result["WEBSITE_CLICKS"].keys()) == ["2026-08-03"]


def test_parse_response_string_value_zero():
    data = {
        "multiDailyMetricTimeSeries": [
            {
                "dailyMetric": "BUSINESS_DIRECTION_REQUESTS",
                "timeSeries": {
                    "datedValues": [
                        {"date": {"year": 2026, "month": 8, "day": 5}, "value": "0"},
                    ]
                },
            }
        ]
    }
    result = _parse_response(data)
    assert result["BUSINESS_DIRECTION_REQUESTS"]["2026-08-05"] == 0


def test_parse_response_unknown_metric_kept():
    data = {
        "multiDailyMetricTimeSeries": [
            {
                "dailyMetric": "FUTURE_METRIC",
                "timeSeries": {"datedValues": [
                    {"date": {"year": 2026, "month": 8, "day": 1}, "value": "3"},
                ]},
            }
        ]
    }
    result = _parse_response(data)
    assert "FUTURE_METRIC" in result


# ---------------------------------------------------------------------------
# PerformanceClient.fetch_daily_metrics
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_session():
    """Patch _AuthSession so PerformanceClient never opens a real socket."""
    session = MagicMock()
    with patch("meo.performance._AuthSession", return_value=session):
        yield session


@pytest.fixture
def client(mock_session):
    return PerformanceClient(MagicMock())


def _ok_response(json_body: dict) -> MagicMock:
    resp = MagicMock()
    resp.ok = True
    resp.raise_for_status.return_value = None
    resp.json.return_value = json_body
    return resp


def test_fetch_daily_metrics_returns_parsed_dict(client, mock_session):
    mock_session.get.return_value = _ok_response(_SAMPLE_RESPONSE)
    result = client.fetch_daily_metrics(
        "accounts/1/locations/42",
        date(2026, 8, 1),
        date(2026, 8, 2),
    )
    assert result["WEBSITE_CLICKS"]["2026-08-01"] == 42
    assert result["CALL_CLICKS"]["2026-08-01"] == 5


def test_fetch_daily_metrics_url_uses_v1_name(client, mock_session):
    mock_session.get.return_value = _ok_response({"multiDailyMetricTimeSeries": []})
    client.fetch_daily_metrics(
        "accounts/999/locations/777",
        date(2026, 1, 1),
        date(2026, 1, 7),
    )
    call_url: str = mock_session.get.call_args[0][0]
    assert "locations/777" in call_url
    assert "businessprofileperformance" in call_url


def test_fetch_daily_metrics_sends_all_metrics_by_default(client, mock_session):
    mock_session.get.return_value = _ok_response({"multiDailyMetricTimeSeries": []})
    client.fetch_daily_metrics(
        "locations/42",
        date(2026, 1, 1),
        date(2026, 1, 7),
    )
    params = mock_session.get.call_args[1]["params"]
    metric_values = [v for k, v in params if k == "dailyMetric"]
    assert set(metric_values) == set(ALL_METRICS)


def test_fetch_daily_metrics_custom_metrics_subset(client, mock_session):
    mock_session.get.return_value = _ok_response({"multiDailyMetricTimeSeries": []})
    client.fetch_daily_metrics(
        "locations/42",
        date(2026, 1, 1),
        date(2026, 1, 7),
        metrics=["WEBSITE_CLICKS"],
    )
    params = mock_session.get.call_args[1]["params"]
    metric_values = [v for k, v in params if k == "dailyMetric"]
    assert metric_values == ["WEBSITE_CLICKS"]


def test_fetch_daily_metrics_sends_date_range_params(client, mock_session):
    mock_session.get.return_value = _ok_response({"multiDailyMetricTimeSeries": []})
    client.fetch_daily_metrics(
        "locations/42",
        date(2026, 7, 14),
        date(2026, 8, 10),
    )
    params = mock_session.get.call_args[1]["params"]
    param_dict = {}
    for k, v in params:
        param_dict.setdefault(k, v)
    assert param_dict["dailyRange.startDate.year"] == 2026
    assert param_dict["dailyRange.startDate.month"] == 7
    assert param_dict["dailyRange.startDate.day"] == 14
    assert param_dict["dailyRange.endDate.year"] == 2026
    assert param_dict["dailyRange.endDate.month"] == 8
    assert param_dict["dailyRange.endDate.day"] == 10


def test_fetch_daily_metrics_raises_on_http_error(client, mock_session):
    bad_resp = MagicMock()
    bad_resp.ok = False
    bad_resp.status_code = 403
    bad_resp.json.return_value = {"error": {"message": "PERMISSION_DENIED"}}
    bad_resp.raise_for_status.side_effect = requests.HTTPError("403 Forbidden")
    bad_resp.text = "Forbidden"
    mock_session.get.return_value = bad_resp
    with pytest.raises(requests.HTTPError):
        client.fetch_daily_metrics("locations/42", date(2026, 1, 1), date(2026, 1, 7))


def test_fetch_daily_metrics_empty_response(client, mock_session):
    mock_session.get.return_value = _ok_response({})
    result = client.fetch_daily_metrics(
        "locations/42",
        date(2026, 1, 1),
        date(2026, 1, 7),
    )
    assert result == {}


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

def test_all_metrics_contains_impressions_and_actions():
    assert set(METRICS_IMPRESSIONS).issubset(set(ALL_METRICS))
    assert set(METRICS_ACTIONS).issubset(set(ALL_METRICS))


def test_impressions_and_actions_disjoint():
    assert set(METRICS_IMPRESSIONS).isdisjoint(set(METRICS_ACTIONS))

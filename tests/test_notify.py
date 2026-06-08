"""Tests for the optional Slack notification module."""

from unittest.mock import MagicMock, patch

import pytest

from meo.notify import send_run_summary, _format_message


# ---------------------------------------------------------------------------
# _format_message unit tests
# ---------------------------------------------------------------------------

def test_format_live_run_header():
    msg = _format_message([], dry_run=False)
    assert "LIVE" in msg


def test_format_dry_run_header():
    msg = _format_message([], dry_run=True)
    assert "DRY RUN" in msg


def test_format_success_store():
    results = [
        {
            "store_key": "the_body_kyoto",
            "post": {"status": "posted", "theme": "季節のお手入れ情報"},
            "reviews": {"replied": 2, "deferred": 0, "errors": []},
        }
    ]
    msg = _format_message(results, dry_run=False)
    assert "the_body_kyoto" in msg
    assert "posted" in msg
    assert "季節のお手入れ情報" in msg
    assert "replies: 2" in msg
    assert "✅" in msg


def test_format_deferred_reviews_shown():
    results = [
        {
            "store_key": "the_body_osaka_shinsaibashi",
            "post": {"status": "posted"},
            "reviews": {"replied": 10, "deferred": 5, "errors": []},
        }
    ]
    msg = _format_message(results, dry_run=False)
    assert "5 deferred" in msg


def test_format_review_errors_shown():
    results = [
        {
            "store_key": "mybear_studio_kyoto",
            "post": {"status": "posted"},
            "reviews": {"replied": 1, "deferred": 0, "errors": ["API error"]},
        }
    ]
    msg = _format_message(results, dry_run=False)
    assert "1 error(s)" in msg
    assert "⚠️" in msg


def test_format_store_level_error():
    results = [
        {"store_key": "the_body_kyoto", "error": "location_id not configured"},
    ]
    msg = _format_message(results, dry_run=False)
    assert "the_body_kyoto" in msg
    assert "location_id not configured" in msg
    assert "⚠️" in msg


def test_format_skipped_post():
    results = [
        {
            "store_key": "the_body_kyoto",
            "post": {"status": "skipped"},
            "reviews": {"replied": 0, "deferred": 0, "errors": []},
        }
    ]
    msg = _format_message(results, dry_run=False)
    assert "skipped" in msg


def test_format_no_post_no_reviews():
    results = [{"store_key": "the_body_kyoto"}]
    msg = _format_message(results, dry_run=False)
    assert "the_body_kyoto" in msg
    assert "no actions" in msg


# ---------------------------------------------------------------------------
# send_run_summary integration tests
# ---------------------------------------------------------------------------

def test_no_op_when_env_var_not_set(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    with patch("meo.notify.requests.post") as mock_post:
        send_run_summary([], dry_run=False)
    mock_post.assert_not_called()


def test_posts_to_webhook_when_set(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    with patch("meo.notify.requests.post", return_value=mock_resp) as mock_post:
        send_run_summary([], dry_run=False)
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert call_kwargs[0][0] == "https://hooks.slack.com/test"
    assert "text" in call_kwargs[1]["json"]


def test_webhook_failure_does_not_raise(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    with patch("meo.notify.requests.post", side_effect=Exception("network error")):
        send_run_summary([], dry_run=False)  # must not raise


def test_webhook_http_error_does_not_raise(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = Exception("403 Forbidden")
    with patch("meo.notify.requests.post", return_value=mock_resp):
        send_run_summary([], dry_run=False)  # must not raise


def test_format_manual_reviews_shown():
    """Manual reviews (held by star threshold) must appear in the Slack message."""
    results = [
        {
            "store_key": "the_body_kyoto",
            "post": {"status": "posted"},
            "reviews": {"replied": 3, "deferred": 0, "manual": 2, "errors": []},
        }
    ]
    msg = _format_message(results, dry_run=False)
    assert "2 need manual reply" in msg


def test_format_manual_reviews_absent_when_zero():
    """When manual==0, the 'need manual reply' phrase must not appear."""
    results = [
        {
            "store_key": "the_body_kyoto",
            "post": {"status": "posted"},
            "reviews": {"replied": 3, "deferred": 0, "manual": 0, "errors": []},
        }
    ]
    msg = _format_message(results, dry_run=False)
    assert "need manual reply" not in msg


def test_payload_contains_store_key(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    results = [{"store_key": "mybear_studio_kyoto", "post": {"status": "posted"}, "reviews": {"replied": 0, "deferred": 0, "errors": []}}]
    with patch("meo.notify.requests.post", return_value=mock_resp) as mock_post:
        send_run_summary(results, dry_run=False)
    sent_text = mock_post.call_args[1]["json"]["text"]
    assert "mybear_studio_kyoto" in sent_text

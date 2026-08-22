"""Tests for meo-error-alert."""

import pytest
import requests
from unittest.mock import patch, MagicMock

from meo.tools.error_alert import (
    run_error_alert,
    _format_alert,
    _send_alert,
    main,
    _DEFAULT_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_STORES = [
    {
        "key": "the_body_osaka_shinsaibashi",
        "name": "THE BODY 大阪 心斎橋店",
        "industry": "beauty_salon",
        "location_id": "accounts/1/locations/1",
        "drive_folder_id": "folder_abc",
    },
    {
        "key": "the_body_kyoto",
        "name": "THE BODY 京都店",
        "industry": "beauty_salon",
        "location_id": "accounts/1/locations/2",
        "drive_folder_id": "folder_xyz",
    },
    {
        "key": "mybear_studio_kyoto",
        "name": "MYBEAR STUDIO 京都店",
        "industry": "fitness_studio",
        "location_id": "accounts/1/locations/3",
        "drive_folder_id": "folder_mbk",
    },
]


def _streak(failures=0, successes=0, error_type=None, error_date=None):
    return {
        "consecutive_failures": failures,
        "consecutive_successes": successes,
        "last_error_type": error_type,
        "last_error_date": error_date,
    }


_ALERT = {
    "store_key": "the_body_kyoto",
    "store_name": "THE BODY 京都店",
    "consecutive_failures": 3,
    "last_error_type": "post_error",
    "last_error_date": "2026-08-07",
}

_TODAY = "2026-08-08 09:00 JST"


# ---------------------------------------------------------------------------
# run_error_alert
# ---------------------------------------------------------------------------

class TestRunErrorAlert:
    def test_no_alerts_when_no_failures(self):
        with patch("meo.tools.error_alert.get_run_streak", return_value=_streak(failures=0)):
            result = run_error_alert(_STORES, threshold=_DEFAULT_THRESHOLD)
        assert result == []

    def test_no_alerts_when_below_threshold(self):
        with patch("meo.tools.error_alert.get_run_streak", return_value=_streak(failures=1)):
            result = run_error_alert(_STORES, threshold=2)
        assert result == []

    def test_alert_when_exactly_at_threshold(self):
        streak = _streak(failures=2, error_type="post_error", error_date="2026-08-07")
        with patch("meo.tools.error_alert.get_run_streak", return_value=streak):
            result = run_error_alert(_STORES[:1], threshold=2)
        assert len(result) == 1
        assert result[0]["store_key"] == "the_body_osaka_shinsaibashi"

    def test_alert_when_above_threshold(self):
        streak = _streak(failures=5, error_type="both_error", error_date="2026-08-07")
        with patch("meo.tools.error_alert.get_run_streak", return_value=streak):
            result = run_error_alert(_STORES[:1], threshold=2)
        assert len(result) == 1
        assert result[0]["consecutive_failures"] == 5

    def test_multiple_stores_above_threshold(self):
        def fake_streak(key):
            if key == "the_body_kyoto":
                return _streak(failures=3, error_type="review_error", error_date="2026-08-07")
            if key == "mybear_studio_kyoto":
                return _streak(failures=2, error_type="post_error", error_date="2026-08-06")
            return _streak(failures=0)

        with patch("meo.tools.error_alert.get_run_streak", side_effect=fake_streak):
            result = run_error_alert(_STORES, threshold=2)
        assert len(result) == 2
        keys = {r["store_key"] for r in result}
        assert keys == {"the_body_kyoto", "mybear_studio_kyoto"}

    def test_alert_contains_store_name(self):
        streak = _streak(failures=2, error_type="post_error", error_date="2026-08-07")
        with patch("meo.tools.error_alert.get_run_streak", return_value=streak):
            result = run_error_alert(_STORES[:1], threshold=2)
        assert result[0]["store_name"] == "THE BODY 大阪 心斎橋店"

    def test_alert_contains_error_type(self):
        streak = _streak(failures=2, error_type="review_error", error_date="2026-08-07")
        with patch("meo.tools.error_alert.get_run_streak", return_value=streak):
            result = run_error_alert(_STORES[:1], threshold=2)
        assert result[0]["last_error_type"] == "review_error"

    def test_alert_contains_error_date(self):
        streak = _streak(failures=2, error_type="post_error", error_date="2026-08-07")
        with patch("meo.tools.error_alert.get_run_streak", return_value=streak):
            result = run_error_alert(_STORES[:1], threshold=2)
        assert result[0]["last_error_date"] == "2026-08-07"

    def test_empty_stores_returns_empty(self):
        result = run_error_alert([], threshold=2)
        assert result == []

    def test_threshold_1_alerts_on_single_failure(self):
        with patch("meo.tools.error_alert.get_run_streak", return_value=_streak(failures=1)):
            result = run_error_alert(_STORES[:1], threshold=1)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _format_alert
# ---------------------------------------------------------------------------

class TestFormatAlert:
    def test_header_includes_count(self):
        out = _format_alert([_ALERT], today=_TODAY)
        assert "1店舗" in out

    def test_header_plural_count(self):
        out = _format_alert([_ALERT, _ALERT], today=_TODAY)
        assert "2店舗" in out

    def test_store_name_in_output(self):
        out = _format_alert([_ALERT], today=_TODAY)
        assert "THE BODY 京都店" in out

    def test_store_key_in_output(self):
        out = _format_alert([_ALERT], today=_TODAY)
        assert "the_body_kyoto" in out

    def test_failure_count_in_output(self):
        out = _format_alert([_ALERT], today=_TODAY)
        assert "3回" in out

    def test_error_type_label_post_error(self):
        out = _format_alert([_ALERT], today=_TODAY)
        assert "投稿エラー" in out

    def test_error_type_label_review_error(self):
        alert = {**_ALERT, "last_error_type": "review_error"}
        out = _format_alert([alert], today=_TODAY)
        assert "レビュー返信エラー" in out

    def test_error_type_label_both_error(self):
        alert = {**_ALERT, "last_error_type": "both_error"}
        out = _format_alert([alert], today=_TODAY)
        assert "投稿・返信エラー" in out

    def test_error_type_label_qa_error(self):
        alert = {**_ALERT, "last_error_type": "qa_error"}
        out = _format_alert([alert], today=_TODAY)
        assert "Q&A回答エラー" in out

    def test_error_type_label_post_qa_error(self):
        alert = {**_ALERT, "last_error_type": "post_qa_error"}
        out = _format_alert([alert], today=_TODAY)
        assert "投稿・Q&Aエラー" in out

    def test_error_type_label_review_qa_error(self):
        alert = {**_ALERT, "last_error_type": "review_qa_error"}
        out = _format_alert([alert], today=_TODAY)
        assert "返信・Q&Aエラー" in out

    def test_error_type_label_all_error(self):
        alert = {**_ALERT, "last_error_type": "all_error"}
        out = _format_alert([alert], today=_TODAY)
        assert "投稿・返信・Q&Aエラー" in out

    def test_error_type_none_shows_fallback(self):
        alert = {**_ALERT, "last_error_type": None}
        out = _format_alert([alert], today=_TODAY)
        assert "不明" in out

    def test_unknown_error_type_falls_back_to_raw_string(self):
        alert = {**_ALERT, "last_error_type": "some_new_error"}
        out = _format_alert([alert], today=_TODAY)
        assert "some_new_error" in out

    def test_error_date_in_output(self):
        out = _format_alert([_ALERT], today=_TODAY)
        assert "2026-08-07" in out

    def test_error_date_none_shows_fallback(self):
        alert = {**_ALERT, "last_error_date": None}
        out = _format_alert([alert], today=_TODAY)
        assert "不明" in out

    def test_generated_date_in_output(self):
        out = _format_alert([_ALERT], today=_TODAY)
        assert _TODAY in out

    def test_footer_hint_in_output(self):
        out = _format_alert([_ALERT], today=_TODAY)
        assert "meo-run" in out

    def test_today_defaults_to_jst_when_none(self):
        out = _format_alert([_ALERT])
        assert "JST" in out


# ---------------------------------------------------------------------------
# _send_alert
# ---------------------------------------------------------------------------

class TestSendAlert:
    def test_no_webhook_url_returns_false(self, monkeypatch):
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        assert _send_alert("test message") is False

    def test_success_returns_true(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        with patch("requests.post", return_value=mock_resp) as mock_post:
            result = _send_alert("test message")
        assert result is True
        mock_post.assert_called_once()

    def test_http_error_returns_false(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("403")
        with patch("requests.post", return_value=mock_resp):
            result = _send_alert("test message")
        assert result is False

    def test_network_error_returns_false(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        with patch("requests.post", side_effect=requests.ConnectionError("timeout")):
            result = _send_alert("test message")
        assert result is False

    def test_sends_json_payload(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        with patch("requests.post", return_value=mock_resp) as mock_post:
            _send_alert("hello slack")
        assert mock_post.call_args.kwargs["json"] == {"text": "hello slack"}


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

class TestMain:
    def _patch_stores(self, monkeypatch):
        monkeypatch.setattr("meo.tools.error_alert.cfg.store_list", lambda: _STORES)

    def test_exits_0_when_no_alerts(self, monkeypatch):
        self._patch_stores(monkeypatch)
        with patch("meo.tools.error_alert.get_run_streak", return_value=_streak(failures=0)):
            with patch("sys.argv", ["meo-error-alert"]):
                with pytest.raises(SystemExit) as exc:
                    main()
        assert exc.value.code == 0

    def test_exits_1_when_alerts_exist(self, monkeypatch):
        self._patch_stores(monkeypatch)
        streak = _streak(failures=3, error_type="post_error", error_date="2026-08-07")
        with patch("meo.tools.error_alert.get_run_streak", return_value=streak), \
             patch("meo.tools.error_alert._send_alert", return_value=True), \
             patch("sys.argv", ["meo-error-alert"]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 1

    def test_dry_run_does_not_send(self, monkeypatch):
        self._patch_stores(monkeypatch)
        streak = _streak(failures=3, error_type="post_error", error_date="2026-08-07")
        with patch("meo.tools.error_alert.get_run_streak", return_value=streak), \
             patch("meo.tools.error_alert._send_alert") as mock_send, \
             patch("sys.argv", ["meo-error-alert", "--dry-run"]):
            with pytest.raises(SystemExit):
                main()
        mock_send.assert_not_called()

    def test_live_mode_sends_alert(self, monkeypatch):
        self._patch_stores(monkeypatch)
        streak = _streak(failures=3, error_type="post_error", error_date="2026-08-07")
        with patch("meo.tools.error_alert.get_run_streak", return_value=streak), \
             patch("meo.tools.error_alert._send_alert", return_value=True) as mock_send, \
             patch("sys.argv", ["meo-error-alert"]):
            with pytest.raises(SystemExit):
                main()
        mock_send.assert_called_once()

    def test_prints_alert_to_stdout(self, monkeypatch, capsys):
        self._patch_stores(monkeypatch)
        streak = _streak(failures=3, error_type="post_error", error_date="2026-08-07")
        with patch("meo.tools.error_alert.get_run_streak", return_value=streak), \
             patch("sys.argv", ["meo-error-alert", "--dry-run"]):
            with pytest.raises(SystemExit):
                main()
        out = capsys.readouterr().out
        assert "エラーアラート" in out

    def test_unknown_store_key_exits_1(self, monkeypatch):
        self._patch_stores(monkeypatch)
        with patch("sys.argv", ["meo-error-alert", "--store", "unknown_key"]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 1

    def test_store_filter_limits_checks(self, monkeypatch):
        self._patch_stores(monkeypatch)
        checked_keys: list[str] = []

        def fake_streak(key):
            checked_keys.append(key)
            return _streak(failures=0)

        with patch("meo.tools.error_alert.get_run_streak", side_effect=fake_streak), \
             patch("sys.argv", ["meo-error-alert", "--store", "the_body_kyoto"]):
            with pytest.raises(SystemExit):
                main()
        assert checked_keys == ["the_body_kyoto"]

    def test_threshold_flag_alerts_at_lower_threshold(self, monkeypatch):
        self._patch_stores(monkeypatch)
        with patch("meo.tools.error_alert.get_run_streak", return_value=_streak(failures=1)), \
             patch("meo.tools.error_alert._send_alert", return_value=True), \
             patch("sys.argv", ["meo-error-alert", "--threshold", "1"]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 1

    def test_threshold_flag_respects_higher_value(self, monkeypatch):
        self._patch_stores(monkeypatch)
        with patch("meo.tools.error_alert.get_run_streak", return_value=_streak(failures=2)), \
             patch("sys.argv", ["meo-error-alert", "--threshold", "5"]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 0

    def test_invalid_threshold_zero_exits_1(self, monkeypatch):
        self._patch_stores(monkeypatch)
        with patch("sys.argv", ["meo-error-alert", "--threshold", "0"]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 1

    def test_no_alerts_prints_notice_to_stderr(self, monkeypatch, capsys):
        self._patch_stores(monkeypatch)
        with patch("meo.tools.error_alert.get_run_streak", return_value=_streak(failures=0)), \
             patch("sys.argv", ["meo-error-alert"]):
            with pytest.raises(SystemExit):
                main()
        err = capsys.readouterr().err
        assert "No consecutive run errors" in err

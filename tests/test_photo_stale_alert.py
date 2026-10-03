"""Tests for meo.tools.photo_stale_alert."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from meo.tools.photo_stale_alert import (
    _DEFAULT_MIN_SAMPLES,
    _DEFAULT_MIN_VARIETY,
    _format_alert,
    _send_alert,
    compute_variety,
    run_photo_stale_alert,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_STORE_A = {
    "key": "the_body_kyoto",
    "name": "THE BODY 京都店",
    "drive_folder_id": "folder_abc",
}
_STORE_B = {
    "key": "mybear_studio_kyoto",
    "name": "MYBEAR STUDIO 京都店",
    "drive_folder_id": "folder_xyz",
}
_STORE_UNCONFIGURED = {
    "key": "the_body_osaka_shinsaibashi",
    "name": "THE BODY 大阪 心斎橋店",
    "drive_folder_id": "TODO: Google Drive folder ID",
}
_STORE_NO_FOLDER = {
    "key": "the_body_osaka_shinsaibashi",
    "name": "THE BODY 大阪 心斎橋店",
    "drive_folder_id": "",
}


# ---------------------------------------------------------------------------
# compute_variety
# ---------------------------------------------------------------------------

class TestComputeVariety:
    def _patch_recent(self, images: list[str]):
        return patch("meo.tools.photo_stale_alert.get_recent_images", return_value=images)

    def test_full_buffer_multiple_unique(self):
        with self._patch_recent(["A", "B", "C", "D", "E"]):
            result = compute_variety([_STORE_A])
        assert len(result) == 1
        assert result[0]["unique_count"] == 5
        assert result[0]["recent_count"] == 5

    def test_full_buffer_low_unique(self):
        with self._patch_recent(["A", "B", "A", "B", "A"]):
            result = compute_variety([_STORE_A])
        assert result[0]["unique_count"] == 2
        assert result[0]["recent_count"] == 5

    def test_full_buffer_single_unique(self):
        with self._patch_recent(["A", "A", "A", "A", "A"]):
            result = compute_variety([_STORE_A])
        assert result[0]["unique_count"] == 1

    def test_not_enough_samples_excluded(self):
        with self._patch_recent(["A", "B", "C"]):
            result = compute_variety([_STORE_A], min_samples=5)
        assert result == []

    def test_exactly_min_samples_included(self):
        with self._patch_recent(["A", "B", "C"]):
            result = compute_variety([_STORE_A], min_samples=3)
        assert len(result) == 1

    def test_empty_recent_excluded(self):
        with self._patch_recent([]):
            result = compute_variety([_STORE_A])
        assert result == []

    def test_unconfigured_folder_excluded(self):
        with self._patch_recent(["A", "B", "C", "D", "E"]):
            result = compute_variety([_STORE_UNCONFIGURED])
        assert result == []

    def test_empty_folder_excluded(self):
        with self._patch_recent(["A", "B", "C", "D", "E"]):
            result = compute_variety([_STORE_NO_FOLDER])
        assert result == []

    def test_multiple_stores(self):
        def mock_recent(store_key: str) -> list[str]:
            if store_key == "the_body_kyoto":
                return ["A", "B", "C", "D", "E"]
            return ["X", "X", "X", "X", "X"]

        with patch("meo.tools.photo_stale_alert.get_recent_images", side_effect=mock_recent):
            result = compute_variety([_STORE_A, _STORE_B])

        assert len(result) == 2
        kyoto = next(r for r in result if r["store_key"] == "the_body_kyoto")
        mybear = next(r for r in result if r["store_key"] == "mybear_studio_kyoto")
        assert kyoto["unique_count"] == 5
        assert mybear["unique_count"] == 1

    def test_result_contains_expected_keys(self):
        with self._patch_recent(["A", "B", "C", "D", "E"]):
            result = compute_variety([_STORE_A])
        row = result[0]
        assert "store_key" in row
        assert "store_name" in row
        assert "folder_id" in row
        assert "recent_count" in row
        assert "unique_count" in row
        assert row["folder_id"] == "folder_abc"
        assert row["store_name"] == "THE BODY 京都店"


# ---------------------------------------------------------------------------
# run_photo_stale_alert
# ---------------------------------------------------------------------------

class TestRunPhotoStaleAlert:
    def _patch_recent(self, images: list[str]):
        return patch("meo.tools.photo_stale_alert.get_recent_images", return_value=images)

    def test_no_alert_when_variety_sufficient(self):
        with self._patch_recent(["A", "B", "C", "D", "E"]):
            alerts = run_photo_stale_alert([_STORE_A], min_variety=3)
        assert alerts == []

    def test_alert_when_unique_below_threshold(self):
        with self._patch_recent(["A", "B", "A", "B", "A"]):
            alerts = run_photo_stale_alert([_STORE_A], min_variety=3)
        assert len(alerts) == 1
        assert alerts[0]["store_key"] == "the_body_kyoto"

    def test_alert_when_unique_equals_threshold_not_triggered(self):
        # unique == min_variety: strictly below → no alert
        with self._patch_recent(["A", "B", "C", "A", "B"]):
            alerts = run_photo_stale_alert([_STORE_A], min_variety=3)
        assert alerts == []

    def test_alert_when_unique_is_one_below_threshold(self):
        # unique=2, min_variety=3 → alert
        with self._patch_recent(["A", "B", "A", "B", "A"]):
            alerts = run_photo_stale_alert([_STORE_A], min_variety=3)
        assert len(alerts) == 1

    def test_not_enough_samples_no_alert(self):
        with self._patch_recent(["A"]):
            alerts = run_photo_stale_alert([_STORE_A], min_samples=5, min_variety=3)
        assert alerts == []

    def test_unconfigured_store_no_alert(self):
        with self._patch_recent(["A", "A", "A", "A", "A"]):
            alerts = run_photo_stale_alert([_STORE_UNCONFIGURED], min_variety=3)
        assert alerts == []

    def test_multi_store_only_bad_one_alerted(self):
        def mock_recent(store_key: str) -> list[str]:
            if store_key == "the_body_kyoto":
                return ["A", "B", "C", "D", "E"]
            return ["X", "X", "X", "X", "X"]

        with patch("meo.tools.photo_stale_alert.get_recent_images", side_effect=mock_recent):
            alerts = run_photo_stale_alert([_STORE_A, _STORE_B], min_variety=3)

        assert len(alerts) == 1
        assert alerts[0]["store_key"] == "mybear_studio_kyoto"

    def test_multi_store_both_bad(self):
        with self._patch_recent(["X", "X", "X", "X", "X"]):
            alerts = run_photo_stale_alert([_STORE_A, _STORE_B], min_variety=3)
        assert len(alerts) == 2

    def test_custom_min_samples(self):
        with self._patch_recent(["A", "A", "A"]):
            alerts_strict = run_photo_stale_alert([_STORE_A], min_samples=5, min_variety=3)
            alerts_loose  = run_photo_stale_alert([_STORE_A], min_samples=3, min_variety=3)
        assert alerts_strict == []
        assert len(alerts_loose) == 1


# ---------------------------------------------------------------------------
# _format_alert
# ---------------------------------------------------------------------------

class TestFormatAlert:
    def _make_alerts(self, unique: int = 1) -> list[dict]:
        return [
            {
                "store_key": "the_body_kyoto",
                "store_name": "THE BODY 京都店",
                "folder_id": "folder_abc",
                "recent_count": 5,
                "unique_count": unique,
            }
        ]

    def test_contains_store_name(self):
        text = _format_alert(self._make_alerts(), min_variety=3)
        assert "THE BODY 京都店" in text

    def test_contains_store_key(self):
        text = _format_alert(self._make_alerts(), min_variety=3)
        assert "the_body_kyoto" in text

    def test_contains_unique_count(self):
        text = _format_alert(self._make_alerts(unique=2), min_variety=3)
        assert "2種" in text

    def test_contains_min_variety(self):
        text = _format_alert(self._make_alerts(), min_variety=3)
        assert "3種" in text

    def test_contains_folder_id(self):
        text = _format_alert(self._make_alerts(), min_variety=3)
        assert "folder_abc" in text

    def test_contains_audit_hint(self):
        text = _format_alert(self._make_alerts(), min_variety=3)
        assert "meo-photo-audit" in text

    def test_header_store_count(self):
        alerts = self._make_alerts() + [
            {
                "store_key": "mybear_studio_kyoto",
                "store_name": "MYBEAR STUDIO 京都店",
                "folder_id": "folder_xyz",
                "recent_count": 5,
                "unique_count": 1,
            }
        ]
        text = _format_alert(alerts, min_variety=3)
        assert "2店舗" in text

    def test_single_store_in_header(self):
        text = _format_alert(self._make_alerts(), min_variety=3)
        assert "1店舗" in text


# ---------------------------------------------------------------------------
# _send_alert
# ---------------------------------------------------------------------------

class TestSendAlert:
    def test_no_webhook_url_returns_false(self, monkeypatch):
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        assert _send_alert("test") is False

    def test_successful_post_returns_true(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.com/test")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        with patch("meo.tools.photo_stale_alert.requests.post", return_value=mock_resp) as mock_post:
            result = _send_alert("test message")
        assert result is True
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs["json"] == {"text": "test message"}

    def test_http_error_returns_false(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.com/test")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("HTTP 500")
        with patch("meo.tools.photo_stale_alert.requests.post", return_value=mock_resp):
            result = _send_alert("test")
        assert result is False

    def test_connection_error_returns_false(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.com/test")
        with patch("meo.tools.photo_stale_alert.requests.post", side_effect=Exception("conn refused")):
            result = _send_alert("test")
        assert result is False


# ---------------------------------------------------------------------------
# main() via sys.argv
# ---------------------------------------------------------------------------

class TestMain:
    def _run(self, argv: list[str], monkeypatch, recent_images=None, stores=None):
        if recent_images is None:
            recent_images = []
        if stores is None:
            stores = [_STORE_A, _STORE_B, _STORE_UNCONFIGURED]

        monkeypatch.setattr("sys.argv", ["meo-photo-stale-alert"] + argv)
        with (
            patch("meo.tools.photo_stale_alert.cfg.store_list", return_value=stores),
            patch("meo.tools.photo_stale_alert.get_recent_images", return_value=recent_images),
        ):
            from meo.tools.photo_stale_alert import main
            with pytest.raises(SystemExit) as exc_info:
                main()
        return exc_info.value.code

    def test_exit_0_when_no_alerts(self, monkeypatch):
        code = self._run([], monkeypatch, recent_images=["A", "B", "C", "D", "E"])
        assert code == 0

    def test_exit_1_when_alerts(self, monkeypatch):
        code = self._run(
            [],
            monkeypatch,
            recent_images=["A", "A", "A", "A", "A"],
            stores=[_STORE_A],
        )
        assert code == 1

    def test_dry_run_skips_slack(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.com/test")
        with patch("meo.tools.photo_stale_alert.requests.post") as mock_post:
            self._run(
                ["--dry-run"],
                monkeypatch,
                recent_images=["A", "A", "A", "A", "A"],
                stores=[_STORE_A],
            )
        mock_post.assert_not_called()

    def test_live_sends_slack(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.com/test")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        with patch("meo.tools.photo_stale_alert.requests.post", return_value=mock_resp) as mock_post:
            self._run(
                [],
                monkeypatch,
                recent_images=["A", "A", "A", "A", "A"],
                stores=[_STORE_A],
            )
        mock_post.assert_called_once()

    def test_store_filter_unknown(self, monkeypatch):
        code = self._run(["--store", "unknown_store"], monkeypatch)
        assert code == 1

    def test_store_filter_valid(self, monkeypatch):
        code = self._run(
            ["--store", "the_body_kyoto"],
            monkeypatch,
            recent_images=["A", "B", "C", "D", "E"],
        )
        assert code == 0

    def test_custom_min_samples(self, monkeypatch):
        # With --min-samples 3, only 3 entries needed to trigger
        code = self._run(
            ["--min-samples", "3", "--min-variety", "3"],
            monkeypatch,
            recent_images=["A", "A", "A"],
            stores=[_STORE_A],
        )
        assert code == 1

    def test_custom_min_variety(self, monkeypatch):
        # 5 unique images, but min-variety set to 6 → alert
        code = self._run(
            ["--min-variety", "6"],
            monkeypatch,
            recent_images=["A", "B", "C", "D", "E"],
            stores=[_STORE_A],
        )
        assert code == 1

    def test_invalid_min_samples_exits_1(self, monkeypatch):
        code = self._run(["--min-samples", "0"], monkeypatch)
        assert code == 1

    def test_invalid_min_variety_exits_1(self, monkeypatch):
        code = self._run(["--min-variety", "0"], monkeypatch)
        assert code == 1

    def test_not_enough_data_exits_0(self, monkeypatch):
        # Only 2 recent images — below default min-samples of 5
        code = self._run(
            [],
            monkeypatch,
            recent_images=["A", "A"],
            stores=[_STORE_A],
        )
        assert code == 0

    def test_unconfigured_folder_exits_0(self, monkeypatch):
        code = self._run(
            [],
            monkeypatch,
            recent_images=["A", "A", "A", "A", "A"],
            stores=[_STORE_UNCONFIGURED],
        )
        assert code == 0

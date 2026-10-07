"""Tests for meo.tools.review_keyword_alert."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from meo.tools.review_keyword_alert import (
    _find_matches,
    _load_watchlist,
    _send_alert,
    _star_symbol,
    format_alert,
    run_keyword_alert,
    scan_store,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_STORE_A = {"key": "the_body_kyoto", "name": "THE BODY 京都店"}
_STORE_B = {"key": "mybear_studio_kyoto", "name": "MYBEAR STUDIO 京都店"}
_STORE_C = {"key": "the_body_osaka_shinsaibashi", "name": "THE BODY 大阪 心斎橋店"}

_WATCHLIST = [
    {"category": "清潔感・衛生", "keywords": ["清潔感", "汚い"]},
    {"category": "待ち時間・混雑", "keywords": ["待ち時間", "混雑"]},
    {"category": "スタッフ対応", "keywords": ["対応が悪い", "無愛想"]},
]

_REVIEW_CLEAN = {
    "review_id": "r001",
    "reviewer": "田中",
    "stars": "ONE",
    "comment": "店内の清潔感がまったくない。汚いし臭います。",
}
_REVIEW_WAIT = {
    "review_id": "r002",
    "reviewer": "鈴木",
    "stars": "TWO",
    "comment": "待ち時間が長すぎます。改善をお願いします。",
}
_REVIEW_POSITIVE = {
    "review_id": "r003",
    "reviewer": "山田",
    "stars": "FIVE",
    "comment": "スタッフが丁寧で素晴らしかった。また来ます！",
}
_REVIEW_NO_COMMENT = {
    "review_id": "r004",
    "reviewer": "匿名",
    "stars": "THREE",
    "comment": "",
}
_REVIEW_NO_COMMENT_NONE = {
    "review_id": "r005",
    "reviewer": "匿名",
    "stars": "TWO",
    "comment": None,
}


# ---------------------------------------------------------------------------
# TestFindMatches
# ---------------------------------------------------------------------------

class TestFindMatches:
    def test_no_match_returns_empty(self):
        result = _find_matches("素晴らしいお店です。", _WATCHLIST)
        assert result == []

    def test_single_keyword_match(self):
        result = _find_matches("清潔感がない店です。", _WATCHLIST)
        assert len(result) == 1
        assert result[0]["category"] == "清潔感・衛生"
        assert result[0]["keyword"] == "清潔感"

    def test_first_keyword_wins_within_category(self):
        # comment contains "汚い" (second keyword) but NOT "清潔感" (first)
        result = _find_matches("汚いお店でした。", _WATCHLIST)
        assert len(result) == 1
        assert result[0]["keyword"] == "汚い"

    def test_multiple_categories_matched(self):
        result = _find_matches("清潔感がなく待ち時間も長い。", _WATCHLIST)
        categories = {m["category"] for m in result}
        assert "清潔感・衛生" in categories
        assert "待ち時間・混雑" in categories
        assert len(result) == 2

    def test_only_one_match_per_category(self):
        # comment contains BOTH "清潔感" and "汚い" from the same category
        result = _find_matches("清潔感がなく汚い。", _WATCHLIST)
        clean_matches = [m for m in result if m["category"] == "清潔感・衛生"]
        assert len(clean_matches) == 1
        assert clean_matches[0]["keyword"] == "清潔感"

    def test_case_insensitive_latin(self):
        # ASCII portions are lowercased before comparison, so "ng" matches "NG"
        watchlist = [{"category": "test", "keywords": ["NGワード"]}]
        assert _find_matches("ngワード", watchlist) != []
        assert _find_matches("NGワード", watchlist) != []

    def test_empty_comment_returns_empty(self):
        assert _find_matches("", _WATCHLIST) == []

    def test_empty_watchlist_returns_empty(self):
        assert _find_matches("清潔感がない", []) == []

    def test_entry_without_keywords_key_skipped(self):
        watchlist = [{"category": "bad", "not_keywords": ["清潔感"]}]
        assert _find_matches("清潔感がない", watchlist) == []

    def test_entry_with_non_list_keywords_skipped(self):
        watchlist = [{"category": "bad", "keywords": "清潔感"}]
        assert _find_matches("清潔感がない", watchlist) == []

    def test_empty_keyword_string_skipped(self):
        watchlist = [{"category": "test", "keywords": ["", "清潔感"]}]
        result = _find_matches("清潔感がない", watchlist)
        assert result[0]["keyword"] == "清潔感"


# ---------------------------------------------------------------------------
# TestLoadWatchlist
# ---------------------------------------------------------------------------

class TestLoadWatchlist:
    def test_returns_list_from_content(self):
        mock_content = {"review_keyword_watchlist": _WATCHLIST}
        with patch("meo.tools.review_keyword_alert.cfg.content", return_value=mock_content):
            result = _load_watchlist()
        assert result == _WATCHLIST

    def test_missing_key_returns_empty(self):
        with patch("meo.tools.review_keyword_alert.cfg.content", return_value={}):
            result = _load_watchlist()
        assert result == []

    def test_non_list_value_returns_empty(self):
        mock_content = {"review_keyword_watchlist": "not a list"}
        with patch("meo.tools.review_keyword_alert.cfg.content", return_value=mock_content):
            result = _load_watchlist()
        assert result == []

    def test_config_exception_returns_empty(self):
        with patch("meo.tools.review_keyword_alert.cfg.content", side_effect=RuntimeError("cfg err")):
            result = _load_watchlist()
        assert result == []


# ---------------------------------------------------------------------------
# TestStarSymbol
# ---------------------------------------------------------------------------

class TestStarSymbol:
    def test_five(self):
        assert _star_symbol("FIVE") == "★★★★★"

    def test_one(self):
        assert _star_symbol("ONE") == "★☆☆☆☆"

    def test_unknown_falls_back_to_raw(self):
        assert _star_symbol("SIX") == "SIX"

    def test_none_falls_back_to_question(self):
        assert _star_symbol("") == "？"


# ---------------------------------------------------------------------------
# TestScanStore
# ---------------------------------------------------------------------------

class TestScanStore:
    def _patch_held(self, reviews):
        return patch("meo.tools.review_keyword_alert.get_held_reviews", return_value=reviews)

    def test_keyword_in_comment_returns_match(self):
        with self._patch_held([_REVIEW_CLEAN]):
            result = scan_store("the_body_kyoto", "THE BODY 京都店", _WATCHLIST)
        categories = {r["category"] for r in result}
        assert "清潔感・衛生" in categories

    def test_positive_review_returns_no_matches(self):
        with self._patch_held([_REVIEW_POSITIVE]):
            result = scan_store("the_body_kyoto", "THE BODY 京都店", _WATCHLIST)
        assert result == []

    def test_empty_comment_skipped(self):
        with self._patch_held([_REVIEW_NO_COMMENT]):
            result = scan_store("the_body_kyoto", "THE BODY 京都店", _WATCHLIST)
        assert result == []

    def test_none_comment_skipped(self):
        with self._patch_held([_REVIEW_NO_COMMENT_NONE]):
            result = scan_store("the_body_kyoto", "THE BODY 京都店", _WATCHLIST)
        assert result == []

    def test_multiple_reviews_multiple_matches(self):
        with self._patch_held([_REVIEW_CLEAN, _REVIEW_WAIT]):
            result = scan_store("the_body_kyoto", "THE BODY 京都店", _WATCHLIST)
        categories = {r["category"] for r in result}
        assert "清潔感・衛生" in categories
        assert "待ち時間・混雑" in categories

    def test_comment_preview_truncated_at_80_chars(self):
        long_comment = "清潔感" + "あ" * 100
        review = {**_REVIEW_CLEAN, "comment": long_comment}
        with self._patch_held([review]):
            result = scan_store("the_body_kyoto", "THE BODY 京都店", _WATCHLIST)
        assert result[0]["comment_preview"].endswith("…")

    def test_comment_short_not_truncated(self):
        short_comment = "清潔感がない"
        review = {**_REVIEW_CLEAN, "comment": short_comment}
        with self._patch_held([review]):
            result = scan_store("the_body_kyoto", "THE BODY 京都店", _WATCHLIST)
        assert not result[0]["comment_preview"].endswith("…")

    def test_result_contains_store_info(self):
        with self._patch_held([_REVIEW_CLEAN]):
            result = scan_store("the_body_kyoto", "THE BODY 京都店", _WATCHLIST)
        assert result[0]["store_key"] == "the_body_kyoto"
        assert result[0]["store_name"] == "THE BODY 京都店"
        assert result[0]["reviewer"] == "田中"
        assert result[0]["stars"] == "ONE"

    def test_empty_held_returns_empty(self):
        with self._patch_held([]):
            result = scan_store("the_body_kyoto", "THE BODY 京都店", _WATCHLIST)
        assert result == []

    def test_empty_watchlist_returns_empty(self):
        with self._patch_held([_REVIEW_CLEAN]):
            result = scan_store("the_body_kyoto", "THE BODY 京都店", [])
        assert result == []


# ---------------------------------------------------------------------------
# TestRunKeywordAlert
# ---------------------------------------------------------------------------

class TestRunKeywordAlert:
    def _patch_held(self, store_to_reviews: dict):
        def fake_get_held(key):
            return store_to_reviews.get(key, [])
        return patch("meo.tools.review_keyword_alert.get_held_reviews", side_effect=fake_get_held)

    def test_no_matches_returns_empty(self):
        held = {"the_body_kyoto": [_REVIEW_POSITIVE]}
        with self._patch_held(held):
            result = run_keyword_alert([_STORE_A], watchlist=_WATCHLIST)
        assert result == []

    def test_match_in_one_store(self):
        held = {
            "the_body_kyoto": [_REVIEW_CLEAN],
            "mybear_studio_kyoto": [_REVIEW_POSITIVE],
        }
        with self._patch_held(held):
            result = run_keyword_alert([_STORE_A, _STORE_B], watchlist=_WATCHLIST)
        assert all(r["store_key"] == "the_body_kyoto" for r in result)

    def test_matches_across_all_stores(self):
        held = {
            "the_body_kyoto": [_REVIEW_WAIT],
            "mybear_studio_kyoto": [_REVIEW_CLEAN],
        }
        with self._patch_held(held):
            result = run_keyword_alert([_STORE_A, _STORE_B], watchlist=_WATCHLIST)
        store_keys = {r["store_key"] for r in result}
        assert "the_body_kyoto" in store_keys
        assert "mybear_studio_kyoto" in store_keys

    def test_empty_stores_returns_empty(self):
        with patch("meo.tools.review_keyword_alert.get_held_reviews", return_value=[]):
            result = run_keyword_alert([], watchlist=_WATCHLIST)
        assert result == []

    def test_empty_watchlist_returns_empty(self):
        held = {"the_body_kyoto": [_REVIEW_CLEAN]}
        with self._patch_held(held):
            result = run_keyword_alert([_STORE_A], watchlist=[])
        assert result == []

    def test_none_watchlist_loads_from_config(self):
        mock_content = {"review_keyword_watchlist": _WATCHLIST}
        held = {"the_body_kyoto": [_REVIEW_CLEAN]}
        with patch("meo.tools.review_keyword_alert.cfg.content", return_value=mock_content):
            with self._patch_held(held):
                result = run_keyword_alert([_STORE_A], watchlist=None)
        assert len(result) > 0

    def test_none_watchlist_empty_config_returns_empty(self):
        with patch("meo.tools.review_keyword_alert.cfg.content", return_value={}):
            with patch("meo.tools.review_keyword_alert.get_held_reviews", return_value=[_REVIEW_CLEAN]):
                result = run_keyword_alert([_STORE_A], watchlist=None)
        assert result == []

    def test_multiple_categories_same_review(self):
        review = {
            "review_id": "r99",
            "reviewer": "複合",
            "stars": "ONE",
            "comment": "清潔感がなく待ち時間も長い最悪",
        }
        held = {"the_body_kyoto": [review]}
        with self._patch_held(held):
            result = run_keyword_alert([_STORE_A], watchlist=_WATCHLIST)
        categories = {r["category"] for r in result}
        assert "清潔感・衛生" in categories
        assert "待ち時間・混雑" in categories


# ---------------------------------------------------------------------------
# TestFormatAlert
# ---------------------------------------------------------------------------

class TestFormatAlert:
    def _make_matches(self, n=1):
        base = {
            "store_key": "the_body_kyoto",
            "store_name": "THE BODY 京都店",
            "review_id": "r001",
            "reviewer": "テスト",
            "stars": "ONE",
            "comment_preview": "清潔感がない",
            "category": "清潔感・衛生",
            "keyword": "清潔感",
        }
        return [dict(base, review_id=f"r{i:03d}") for i in range(n)]

    def test_contains_store_name(self):
        msg = format_alert(self._make_matches())
        assert "THE BODY 京都店" in msg

    def test_contains_category(self):
        msg = format_alert(self._make_matches())
        assert "清潔感・衛生" in msg

    def test_contains_keyword(self):
        msg = format_alert(self._make_matches())
        assert "清潔感" in msg

    def test_contains_comment_preview(self):
        msg = format_alert(self._make_matches())
        assert "清潔感がない" in msg

    def test_header_mentions_store_count(self):
        msg = format_alert(self._make_matches())
        assert "1店舗" in msg

    def test_header_mentions_review_count(self):
        # Two match entries for the same (store_key, review_id) → counts as 1 unique review
        base = self._make_matches(1)[0]
        m1 = {**base, "category": "清潔感・衛生", "keyword": "清潔感"}
        m2 = {**base, "category": "待ち時間・混雑", "keyword": "待ち時間"}
        msg = format_alert([m1, m2])
        assert "1件" in msg

    def test_two_stores_in_header(self):
        m1 = {
            "store_key": "the_body_kyoto", "store_name": "THE BODY 京都店",
            "review_id": "r1", "reviewer": "A", "stars": "ONE",
            "comment_preview": "清潔感がない", "category": "清潔感・衛生", "keyword": "清潔感",
        }
        m2 = {
            "store_key": "mybear_studio_kyoto", "store_name": "MYBEAR STUDIO 京都店",
            "review_id": "r2", "reviewer": "B", "stars": "TWO",
            "comment_preview": "待ち時間が長い", "category": "待ち時間・混雑", "keyword": "待ち時間",
        }
        msg = format_alert([m1, m2])
        assert "2店舗" in msg

    def test_contains_star_symbol(self):
        msg = format_alert(self._make_matches())
        assert "★" in msg

    def test_contains_call_to_action(self):
        msg = format_alert(self._make_matches())
        assert "確認" in msg


# ---------------------------------------------------------------------------
# TestSendAlert
# ---------------------------------------------------------------------------

class TestSendAlert:
    def test_no_url_returns_false(self, monkeypatch):
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        assert _send_alert("test") is False

    def test_success_returns_true(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        with patch("meo.tools.review_keyword_alert.requests.post", return_value=mock_resp) as mock_post:
            result = _send_alert("alert message")
        assert result is True
        mock_post.assert_called_once()

    def test_http_error_returns_false(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = __import__("requests").HTTPError("500")
        with patch("meo.tools.review_keyword_alert.requests.post", return_value=mock_resp):
            result = _send_alert("alert")
        assert result is False

    def test_connection_error_returns_false(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        with patch("meo.tools.review_keyword_alert.requests.post", side_effect=ConnectionError("no connection")):
            result = _send_alert("alert")
        assert result is False


# ---------------------------------------------------------------------------
# TestMain
# ---------------------------------------------------------------------------

class TestMain:
    def _patch_stores(self):
        return patch(
            "meo.tools.review_keyword_alert.cfg.store_list",
            return_value=[_STORE_A, _STORE_B, _STORE_C],
        )

    def _patch_content(self, watchlist=None):
        if watchlist is None:
            watchlist = _WATCHLIST
        return patch(
            "meo.tools.review_keyword_alert.cfg.content",
            return_value={"review_keyword_watchlist": watchlist},
        )

    def _patch_held(self, reviews_by_key: dict):
        def fake_held(key):
            return reviews_by_key.get(key, [])
        return patch("meo.tools.review_keyword_alert.get_held_reviews", side_effect=fake_held)

    def test_exit_0_when_no_matches(self, monkeypatch):
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        held = {"the_body_kyoto": [_REVIEW_POSITIVE]}
        with self._patch_stores(), self._patch_content(), self._patch_held(held):
            with pytest.raises(SystemExit) as exc:
                from meo.tools import review_keyword_alert
                import importlib
                monkeypatch.setattr(sys, "argv", ["meo-review-keyword-alert"])
                review_keyword_alert.main()
        assert exc.value.code == 0

    def test_exit_1_when_match_found(self, monkeypatch):
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        held = {"the_body_kyoto": [_REVIEW_CLEAN]}
        with self._patch_stores(), self._patch_content(), self._patch_held(held):
            with pytest.raises(SystemExit) as exc:
                monkeypatch.setattr(sys, "argv", ["meo-review-keyword-alert"])
                from meo.tools import review_keyword_alert
                review_keyword_alert.main()
        assert exc.value.code == 1

    def test_dry_run_skips_slack(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        held = {"the_body_kyoto": [_REVIEW_CLEAN]}
        with self._patch_stores(), self._patch_content(), self._patch_held(held):
            with patch("meo.tools.review_keyword_alert.requests.post") as mock_post:
                with pytest.raises(SystemExit):
                    monkeypatch.setattr(sys, "argv", ["meo-review-keyword-alert", "--dry-run"])
                    from meo.tools import review_keyword_alert
                    review_keyword_alert.main()
        mock_post.assert_not_called()

    def test_live_run_sends_to_slack(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        held = {"the_body_kyoto": [_REVIEW_CLEAN]}
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        with self._patch_stores(), self._patch_content(), self._patch_held(held):
            with patch("meo.tools.review_keyword_alert.requests.post", return_value=mock_resp) as mock_post:
                with pytest.raises(SystemExit):
                    monkeypatch.setattr(sys, "argv", ["meo-review-keyword-alert"])
                    from meo.tools import review_keyword_alert
                    review_keyword_alert.main()
        mock_post.assert_called_once()

    def test_store_filter_limits_check(self, monkeypatch):
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        held = {
            "the_body_kyoto": [_REVIEW_CLEAN],
            "mybear_studio_kyoto": [_REVIEW_WAIT],
        }
        with self._patch_stores(), self._patch_content(), self._patch_held(held):
            with pytest.raises(SystemExit) as exc:
                monkeypatch.setattr(sys, "argv", ["meo-review-keyword-alert", "--store", "mybear_studio_kyoto"])
                from meo.tools import review_keyword_alert
                review_keyword_alert.main()
        # only mybear checked — both stores had matches but only mybear scanned
        assert exc.value.code == 1

    def test_unknown_store_exits_1(self, monkeypatch):
        with self._patch_stores():
            with pytest.raises(SystemExit) as exc:
                monkeypatch.setattr(sys, "argv", ["meo-review-keyword-alert", "--store", "unknown_store"])
                from meo.tools import review_keyword_alert
                review_keyword_alert.main()
        assert exc.value.code == 1

    def test_no_watchlist_configured_exits_0(self, monkeypatch):
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        with self._patch_stores(), self._patch_content(watchlist=[]):
            with pytest.raises(SystemExit) as exc:
                monkeypatch.setattr(sys, "argv", ["meo-review-keyword-alert"])
                from meo.tools import review_keyword_alert
                review_keyword_alert.main()
        assert exc.value.code == 0

    def test_store_filter_clean_store_exits_0(self, monkeypatch):
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        # the_body_kyoto has a keyword hit, but we only check mybear which is positive
        held = {
            "the_body_kyoto": [_REVIEW_CLEAN],
            "mybear_studio_kyoto": [_REVIEW_POSITIVE],
        }
        with self._patch_stores(), self._patch_content(), self._patch_held(held):
            with pytest.raises(SystemExit) as exc:
                monkeypatch.setattr(sys, "argv", ["meo-review-keyword-alert", "--store", "mybear_studio_kyoto"])
                from meo.tools import review_keyword_alert
                review_keyword_alert.main()
        assert exc.value.code == 0

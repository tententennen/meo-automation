"""Tests for meo.tools.review_alert — Slack alert for held reviews."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from meo.tools.review_alert import (
    _COMMENT_PREVIEW_LEN,
    _format_alert,
    _send_alert,
    _star_symbol,
    run_review_alert,
    main,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_STORES = [
    {"key": "the_body_osaka_shinsaibashi", "name": "THE BODY 大阪 心斎橋店", "industry": "beauty_salon"},
    {"key": "the_body_kyoto", "name": "THE BODY 京都店", "industry": "beauty_salon"},
    {"key": "mybear_studio_kyoto", "name": "MYBEAR STUDIO 京都店", "industry": "fitness_studio"},
]

_HELD_OSAKA = [
    {
        "review_id": "rev_001",
        "reviewer": "田中様",
        "stars": "ONE",
        "comment": "期待していたほどではありませんでした。スタッフの対応に改善が必要だと感じます。",
        "review_date": "2026-07-25",
    },
    {
        "review_id": "rev_002",
        "reviewer": "佐藤様",
        "stars": "TWO",
        "comment": "少し待ち時間が長かったです。",
        "review_date": "2026-07-26",
    },
]

_HELD_KYOTO = [
    {
        "review_id": "rev_003",
        "reviewer": "鈴木様",
        "stars": "TWO",
        "comment": "サービスの質がイマイチでした。",
        "review_date": "2026-07-27",
    },
]


@pytest.fixture(autouse=True)
def _patch_stores(monkeypatch):
    monkeypatch.setattr("meo.tools.review_alert.cfg.store_list", lambda: list(_STORES))


@pytest.fixture(autouse=True)
def _no_held_reviews(monkeypatch):
    """Default: no held reviews for any store."""
    monkeypatch.setattr("meo.tools.review_alert.get_held_reviews", lambda key: [])


# ---------------------------------------------------------------------------
# _star_symbol
# ---------------------------------------------------------------------------

def test_star_symbol_five_returns_five_filled():
    assert _star_symbol("FIVE") == "★★★★★"


def test_star_symbol_one_returns_one_filled():
    assert _star_symbol("ONE") == "★☆☆☆☆"


def test_star_symbol_three_returns_three_filled():
    assert _star_symbol("THREE") == "★★★☆☆"


def test_star_symbol_unknown_returns_raw_value():
    assert _star_symbol("UNKNOWN_RATING") == "UNKNOWN_RATING"


def test_star_symbol_empty_string_returns_fallback():
    result = _star_symbol("")
    assert result == "？"


def test_star_symbol_lowercase_accepted():
    assert _star_symbol("four") == "★★★★☆"


# ---------------------------------------------------------------------------
# run_review_alert — result shape
# ---------------------------------------------------------------------------

def test_run_review_alert_no_held_reviews_returns_empty(monkeypatch):
    result = run_review_alert()
    assert result["total_held"] == 0
    assert result["stores_with_held"] == []


def test_run_review_alert_one_store_with_held_reviews(monkeypatch):
    monkeypatch.setattr(
        "meo.tools.review_alert.get_held_reviews",
        lambda key: _HELD_OSAKA if key == "the_body_osaka_shinsaibashi" else [],
    )
    result = run_review_alert()
    assert result["total_held"] == 2
    assert len(result["stores_with_held"]) == 1
    assert result["stores_with_held"][0]["store_key"] == "the_body_osaka_shinsaibashi"


def test_run_review_alert_multiple_stores_with_held_reviews(monkeypatch):
    def _held(key):
        if key == "the_body_osaka_shinsaibashi":
            return _HELD_OSAKA
        if key == "the_body_kyoto":
            return _HELD_KYOTO
        return []

    monkeypatch.setattr("meo.tools.review_alert.get_held_reviews", _held)
    result = run_review_alert()
    assert result["total_held"] == 3  # 2 + 1
    assert len(result["stores_with_held"]) == 2


def test_run_review_alert_result_includes_store_name(monkeypatch):
    monkeypatch.setattr(
        "meo.tools.review_alert.get_held_reviews",
        lambda key: _HELD_KYOTO if key == "the_body_kyoto" else [],
    )
    result = run_review_alert()
    block = result["stores_with_held"][0]
    assert block["store_name"] == "THE BODY 京都店"


def test_run_review_alert_result_includes_review_entries(monkeypatch):
    monkeypatch.setattr(
        "meo.tools.review_alert.get_held_reviews",
        lambda key: _HELD_OSAKA if key == "the_body_osaka_shinsaibashi" else [],
    )
    result = run_review_alert()
    reviews = result["stores_with_held"][0]["reviews"]
    assert len(reviews) == 2
    assert reviews[0]["reviewer"] == "田中様"


def test_run_review_alert_store_filter_limits_results(monkeypatch):
    def _held(key):
        if key == "the_body_osaka_shinsaibashi":
            return _HELD_OSAKA
        if key == "the_body_kyoto":
            return _HELD_KYOTO
        return []

    monkeypatch.setattr("meo.tools.review_alert.get_held_reviews", _held)
    result = run_review_alert(["the_body_kyoto"])
    assert result["total_held"] == 1
    assert result["stores_with_held"][0]["store_key"] == "the_body_kyoto"


def test_run_review_alert_store_filter_excludes_unchecked_stores(monkeypatch):
    monkeypatch.setattr(
        "meo.tools.review_alert.get_held_reviews",
        lambda key: _HELD_OSAKA if key == "the_body_osaka_shinsaibashi" else [],
    )
    # Filter to kyoto only — osaka should not appear even though it has reviews.
    result = run_review_alert(["the_body_kyoto"])
    assert result["total_held"] == 0


# ---------------------------------------------------------------------------
# _format_alert
# ---------------------------------------------------------------------------

_SAMPLE_RESULT = {
    "total_held": 2,
    "stores_with_held": [
        {
            "store_key": "the_body_osaka_shinsaibashi",
            "store_name": "THE BODY 大阪 心斎橋店",
            "reviews": _HELD_OSAKA,
        }
    ],
}


def test_format_alert_header_contains_total_count():
    text = _format_alert(_SAMPLE_RESULT)
    assert "2件" in text


def test_format_alert_header_contains_alert_label():
    text = _format_alert(_SAMPLE_RESULT)
    assert "MEO レビューアラート" in text


def test_format_alert_contains_store_name():
    text = _format_alert(_SAMPLE_RESULT)
    assert "THE BODY 大阪 心斎橋店" in text


def test_format_alert_contains_store_key():
    text = _format_alert(_SAMPLE_RESULT)
    assert "the_body_osaka_shinsaibashi" in text


def test_format_alert_contains_reviewer_name():
    text = _format_alert(_SAMPLE_RESULT)
    assert "田中様" in text
    assert "佐藤様" in text


def test_format_alert_contains_star_symbol():
    text = _format_alert(_SAMPLE_RESULT)
    assert "★☆☆☆☆" in text  # ONE star for 田中様
    assert "★★☆☆☆" in text  # TWO stars for 佐藤様


def test_format_alert_contains_review_date():
    text = _format_alert(_SAMPLE_RESULT)
    assert "2026-07-25" in text


def test_format_alert_contains_comment_preview():
    text = _format_alert(_SAMPLE_RESULT)
    assert "期待していたほどではありませんでした" in text


def test_format_alert_long_comment_is_truncated():
    # Build a comment where the prefix and suffix are visually distinct
    # so we can verify the suffix is absent in the formatted output.
    prefix = "A" * _COMMENT_PREVIEW_LEN
    suffix = "ZZZTAIL"
    long_comment = prefix + suffix
    result = {
        "total_held": 1,
        "stores_with_held": [
            {
                "store_key": "the_body_kyoto",
                "store_name": "THE BODY 京都店",
                "reviews": [
                    {
                        "review_id": "x1",
                        "reviewer": "お客様",
                        "stars": "ONE",
                        "comment": long_comment,
                        "review_date": "2026-07-27",
                    }
                ],
            }
        ],
    }
    text = _format_alert(result)
    # Truncated comment ends with ellipsis.
    assert "…」" in text
    # The unique tail of the long comment must NOT appear.
    assert suffix not in text


def test_format_alert_short_comment_not_truncated():
    short_comment = "良くなかった"
    result = {
        "total_held": 1,
        "stores_with_held": [
            {
                "store_key": "the_body_kyoto",
                "store_name": "THE BODY 京都店",
                "reviews": [
                    {
                        "review_id": "x2",
                        "reviewer": "お客様",
                        "stars": "TWO",
                        "comment": short_comment,
                        "review_date": "2026-07-27",
                    }
                ],
            }
        ],
    }
    text = _format_alert(result)
    assert short_comment in text
    # No ellipsis for short comments.
    assert "…」" not in text


def test_format_alert_no_comment_omits_comment_line():
    result = {
        "total_held": 1,
        "stores_with_held": [
            {
                "store_key": "the_body_kyoto",
                "store_name": "THE BODY 京都店",
                "reviews": [
                    {
                        "review_id": "x3",
                        "reviewer": "お客様",
                        "stars": "THREE",
                        "comment": "",
                        "review_date": "2026-07-27",
                    }
                ],
            }
        ],
    }
    text = _format_alert(result)
    # Reviewer name present but no comment quotation marks.
    assert "お客様" in text
    assert "「」" not in text


def test_format_alert_anonymous_reviewer_shown_as_placeholder():
    result = {
        "total_held": 1,
        "stores_with_held": [
            {
                "store_key": "the_body_kyoto",
                "store_name": "THE BODY 京都店",
                "reviews": [
                    {
                        "review_id": "x4",
                        "reviewer": "",
                        "stars": "ONE",
                        "comment": "微妙でした",
                        "review_date": "2026-07-27",
                    }
                ],
            }
        ],
    }
    text = _format_alert(result)
    assert "（匿名）" in text


def test_format_alert_footer_contains_export_command():
    text = _format_alert(_SAMPLE_RESULT)
    assert "meo-export held-reviews" in text


def test_format_alert_multiple_stores_each_appear():
    result = {
        "total_held": 3,
        "stores_with_held": [
            {
                "store_key": "the_body_osaka_shinsaibashi",
                "store_name": "THE BODY 大阪 心斎橋店",
                "reviews": _HELD_OSAKA,
            },
            {
                "store_key": "the_body_kyoto",
                "store_name": "THE BODY 京都店",
                "reviews": _HELD_KYOTO,
            },
        ],
    }
    text = _format_alert(result)
    assert "THE BODY 大阪 心斎橋店" in text
    assert "THE BODY 京都店" in text
    assert "鈴木様" in text


def test_format_alert_review_uses_review_date_field(monkeypatch):
    result = {
        "total_held": 1,
        "stores_with_held": [
            {
                "store_key": "the_body_kyoto",
                "store_name": "THE BODY 京都店",
                "reviews": [
                    {
                        "review_id": "x5",
                        "reviewer": "お客様",
                        "stars": "ONE",
                        "comment": "微妙",
                        "review_date": "2026-07-20",
                        "date": "2026-07-01",  # older snapshot date; review_date takes priority
                    }
                ],
            }
        ],
    }
    text = _format_alert(result)
    assert "2026-07-20" in text
    assert "2026-07-01" not in text


def test_format_alert_falls_back_to_date_when_review_date_absent(monkeypatch):
    result = {
        "total_held": 1,
        "stores_with_held": [
            {
                "store_key": "the_body_kyoto",
                "store_name": "THE BODY 京都店",
                "reviews": [
                    {
                        "review_id": "x6",
                        "reviewer": "お客様",
                        "stars": "ONE",
                        "comment": "微妙",
                        "date": "2026-07-15",
                    }
                ],
            }
        ],
    }
    text = _format_alert(result)
    assert "2026-07-15" in text


# ---------------------------------------------------------------------------
# _send_alert
# ---------------------------------------------------------------------------

def test_send_alert_no_webhook_url_returns_false(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    assert _send_alert("test message") is False


def test_send_alert_success_returns_true(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    with patch("meo.tools.review_alert.requests.post", return_value=mock_resp) as mock_post:
        result = _send_alert("test message")
    assert result is True
    mock_post.assert_called_once()


def test_send_alert_http_error_returns_false(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = Exception("500 Server Error")
    with patch("meo.tools.review_alert.requests.post", return_value=mock_resp):
        result = _send_alert("test message")
    assert result is False


def test_send_alert_network_error_returns_false(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    with patch("meo.tools.review_alert.requests.post", side_effect=ConnectionError("network")):
        result = _send_alert("test message")
    assert result is False


def test_send_alert_posts_json_with_text(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    with patch("meo.tools.review_alert.requests.post", return_value=mock_resp) as mock_post:
        _send_alert("alert text")
    _, kwargs = mock_post.call_args
    assert kwargs["json"] == {"text": "alert text"}


# ---------------------------------------------------------------------------
# main() — exit codes and output
# ---------------------------------------------------------------------------

def test_main_no_held_reviews_exits_0(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["meo-review-alert"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


def test_main_held_reviews_exits_1(monkeypatch, capsys):
    monkeypatch.setattr(
        "meo.tools.review_alert.get_held_reviews",
        lambda key: _HELD_OSAKA if key == "the_body_osaka_shinsaibashi" else [],
    )
    monkeypatch.setattr(sys, "argv", ["meo-review-alert"])
    with patch("meo.tools.review_alert._send_alert") as mock_send:
        mock_send.return_value = True
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 1


def test_main_dry_run_prints_alert_without_sending(monkeypatch, capsys):
    monkeypatch.setattr(
        "meo.tools.review_alert.get_held_reviews",
        lambda key: _HELD_OSAKA if key == "the_body_osaka_shinsaibashi" else [],
    )
    monkeypatch.setattr(sys, "argv", ["meo-review-alert", "--dry-run"])
    with patch("meo.tools.review_alert._send_alert") as mock_send:
        with pytest.raises(SystemExit):
            main()
        mock_send.assert_not_called()


def test_main_dry_run_alert_text_is_printed(monkeypatch, capsys):
    monkeypatch.setattr(
        "meo.tools.review_alert.get_held_reviews",
        lambda key: _HELD_OSAKA if key == "the_body_osaka_shinsaibashi" else [],
    )
    monkeypatch.setattr(sys, "argv", ["meo-review-alert", "--dry-run"])
    with pytest.raises(SystemExit):
        main()
    out = capsys.readouterr().out
    assert "MEO レビューアラート" in out
    assert "田中様" in out


def test_main_live_calls_send_alert(monkeypatch, capsys):
    monkeypatch.setattr(
        "meo.tools.review_alert.get_held_reviews",
        lambda key: _HELD_OSAKA if key == "the_body_osaka_shinsaibashi" else [],
    )
    monkeypatch.setattr(sys, "argv", ["meo-review-alert"])
    with patch("meo.tools.review_alert._send_alert", return_value=True) as mock_send:
        with pytest.raises(SystemExit):
            main()
    mock_send.assert_called_once()


def test_main_unknown_store_key_exits_1(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["meo-review-alert", "--store", "nonexistent_store"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "nonexistent_store" in err


def test_main_store_filter_only_checks_given_stores(monkeypatch, capsys):
    call_log: list[str] = []

    def _held(key: str):
        call_log.append(key)
        return []

    monkeypatch.setattr("meo.tools.review_alert.get_held_reviews", _held)
    monkeypatch.setattr(sys, "argv", ["meo-review-alert", "--store", "the_body_kyoto"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    assert call_log == ["the_body_kyoto"]
    assert "the_body_osaka_shinsaibashi" not in call_log


def test_main_no_held_reviews_prints_notice_to_stderr(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["meo-review-alert"])
    with pytest.raises(SystemExit):
        main()
    err = capsys.readouterr().err
    assert "No held reviews" in err

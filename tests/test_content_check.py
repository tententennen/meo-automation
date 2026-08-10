"""Tests for meo-content-check content quality tool."""

from __future__ import annotations

import json
import sys
from unittest.mock import patch

import pytest

from meo.tools.content_check import (
    _OPENING_CHARS,
    _find_repeated_openings,
    _format_output,
    _japanese_ratio,
    _opening_phrase,
    _post_metrics,
    main,
    run_content_check,
)


# ---------------------------------------------------------------------------
# _japanese_ratio
# ---------------------------------------------------------------------------

class TestJapaneseRatio:
    def test_empty_string_returns_zero(self):
        assert _japanese_ratio("") == 0.0

    def test_pure_hiragana(self):
        assert _japanese_ratio("あいうえお") == 1.0

    def test_pure_katakana(self):
        assert _japanese_ratio("アイウエオ") == 1.0

    def test_pure_kanji(self):
        assert _japanese_ratio("日本語") == 1.0

    def test_pure_ascii_is_zero(self):
        assert _japanese_ratio("hello world") == 0.0

    def test_mixed_half_japanese(self):
        # "あaあa" — 2 Japanese (hiragana), 2 ASCII
        assert _japanese_ratio("あaあa") == 0.5

    def test_spaces_are_not_japanese(self):
        assert _japanese_ratio("  ") == 0.0

    def test_japanese_punctuation_not_counted(self):
        # U+3002 (。), U+FF01 (！), U+FF1F (？) are outside _JP_RANGES
        assert _japanese_ratio("。！？") == 0.0

    def test_real_japanese_text_above_threshold(self):
        text = "今月もご来店いただきありがとうございます。新しいメニューをぜひお試しください。"
        assert _japanese_ratio(text) > 0.85

    def test_ratio_bounded_between_zero_and_one(self):
        for text in ["あ", "a", "あa", "日本語テスト"]:
            ratio = _japanese_ratio(text)
            assert 0.0 <= ratio <= 1.0

    def test_katakana_longvowel_counted(self):
        # ー (U+30FC) is in Katakana block (U+30A0–U+30FF) — counted
        assert _japanese_ratio("ラーメン") == 1.0


# ---------------------------------------------------------------------------
# _opening_phrase
# ---------------------------------------------------------------------------

class TestOpeningPhrase:
    def test_first_sentence_with_kuten(self):
        # 。terminates the first sentence; the rest is discarded
        text = "今月のキャンペーン情報をお届けします。詳細はこちらをご覧ください。"
        assert _opening_phrase(text) == "今月のキャンペーン情報をお届けします。"

    def test_stops_at_exclamation(self):
        text = "新しいコースが始まりました！詳細はこちら。"
        assert _opening_phrase(text) == "新しいコースが始まりました！"

    def test_stops_at_newline(self):
        text = "一行目です\n二行目です\n三行目です"
        assert _opening_phrase(text) == "一行目です"

    def test_no_sentence_end_returns_truncated(self):
        # No punctuation within _OPENING_CHARS characters — return first _OPENING_CHARS
        text = "A" * 60
        result = _opening_phrase(text)
        assert len(result) == _OPENING_CHARS

    def test_empty_text_returns_empty(self):
        assert _opening_phrase("") == ""

    def test_strips_whitespace(self):
        text = "こんにちは。 次の文章です。"
        assert _opening_phrase(text) == "こんにちは。"


# ---------------------------------------------------------------------------
# _find_repeated_openings
# ---------------------------------------------------------------------------

class TestFindRepeatedOpenings:
    def test_empty_list_returns_empty(self):
        assert _find_repeated_openings([]) == []

    def test_single_post_no_pairs(self):
        posts = [{"text": "こんにちは、今月のキャンペーン情報です。"}]
        assert _find_repeated_openings(posts) == []

    def test_unique_openings_no_pairs(self):
        posts = [
            {"text": "今月のキャンペーン情報をお届けします。詳細A"},
            {"text": "秋の特別メニューのご紹介です。詳細B"},
            {"text": "スタッフ一同お待ちしております。詳細C"},
        ]
        assert _find_repeated_openings(posts) == []

    def test_repeated_opening_detected(self):
        # Both share first sentence — sentence-boundary detection catches it
        same = "今月のキャンペーン情報をお届けします。"
        posts = [
            {"text": same + "詳細はこちら。" * 5},
            {"text": same + "ぜひご来店ください。" * 5},
        ]
        pairs = _find_repeated_openings(posts)
        assert len(pairs) == 1
        assert pairs[0] == (0, 1)

    def test_empty_text_skipped(self):
        same = "今月のキャンペーン情報をお届けします。"
        posts = [
            {"text": ""},
            {"text": same + "詳細A" * 5},
            {"text": same + "詳細B" * 5},
        ]
        pairs = _find_repeated_openings(posts)
        assert len(pairs) == 1
        assert pairs[0] == (1, 2)

    def test_fallback_to_char_truncation_when_no_sentence_end(self):
        # Texts with no punctuation — compared by first _OPENING_CHARS chars
        prefix = "A" * _OPENING_CHARS
        posts = [
            {"text": prefix + "unique suffix one"},
            {"text": prefix + "unique suffix two"},
        ]
        assert len(_find_repeated_openings(posts)) == 1

    def test_different_first_sentences_no_pair(self):
        posts = [
            {"text": "Aから始まる文章です。続きがあります。"},
            {"text": "Bから始まる文章です。続きがあります。"},
        ]
        assert _find_repeated_openings(posts) == []

    def test_missing_text_key_skipped(self):
        posts = [{"text": "同じ書き出しの投稿です。長い本文が続きます。"}, {}]
        # Second post has no text → empty opening → skipped
        assert _find_repeated_openings(posts) == []


# ---------------------------------------------------------------------------
# _post_metrics
# ---------------------------------------------------------------------------

class TestPostMetrics:
    def test_normal_japanese_post_no_concerns(self):
        text = "秋のお手入れについてご案内します。" * 10
        post = {"date": "2026-08-01", "theme": "秋のケア", "text": text}
        result = _post_metrics(post, max_chars=500)
        assert result["date"] == "2026-08-01"
        assert result["theme"] == "秋のケア"
        assert result["char_count"] == len(text)
        assert result["jp_ratio"] > 0.8
        assert result["concerns"] == []

    def test_short_post_flags_concern(self):
        # max_chars=500, threshold=30% → need ≥150 chars; "短い"=2 chars → concern
        post = {"date": "2026-08-01", "theme": "テスト", "text": "短い"}
        result = _post_metrics(post, max_chars=500)
        assert any("短すぎる" in c for c in result["concerns"])

    def test_low_jp_ratio_flags_concern(self):
        post = {"date": "2026-08-01", "theme": "test", "text": "english only text " * 10}
        result = _post_metrics(post, max_chars=50)
        assert any("日本語率" in c for c in result["concerns"])

    def test_empty_text_flags_both_concerns(self):
        post = {"date": "2026-08-01", "theme": "", "text": ""}
        result = _post_metrics(post, max_chars=500)
        assert result["char_count"] == 0
        assert result["jp_ratio"] == 0.0
        # Both short and low-JP concerns expected
        assert any("短すぎる" in c for c in result["concerns"])
        assert any("日本語率" in c for c in result["concerns"])

    def test_max_chars_zero_suppresses_short_concern(self):
        post = {"date": "2026-08-01", "theme": "", "text": "短い"}
        result = _post_metrics(post, max_chars=0)
        assert not any("短すぎる" in c for c in result["concerns"])

    def test_missing_fields_return_defaults(self):
        result = _post_metrics({}, max_chars=100)
        assert result["date"] == ""
        assert result["theme"] == ""
        assert result["text"] == ""

    def test_jp_ratio_rounded_to_three_decimal_places(self):
        result = _post_metrics({"text": "あaあaあ"}, max_chars=0)
        # 3 Japanese out of 5 → 0.6
        assert result["jp_ratio"] == 0.6


# ---------------------------------------------------------------------------
# run_content_check
# ---------------------------------------------------------------------------

_STORE = [{"key": "test_store", "name": "テスト店", "industry": "beauty_salon"}]
_DEFAULTS = {"max_post_chars": 500}


class TestRunContentCheck:
    def _patch(self, posts, defaults=None):
        return (
            patch("meo.tools.content_check.get_post_history", return_value=posts),
            patch("meo.tools.content_check.cfg.effective_defaults", return_value=defaults or _DEFAULTS),
        )

    def test_empty_history(self):
        p1, p2 = self._patch([])
        with p1, p2:
            results = run_content_check(_STORE)
        assert len(results) == 1
        assert results[0]["posts"] == []
        assert results[0]["has_concerns"] is False
        assert results[0]["repeated_openings"] == []

    def test_clean_history_no_concerns(self):
        posts = [
            {"date": "2026-08-01", "theme": "秋のケア", "text": "秋のお手入れ。" * 30},
            {"date": "2026-07-31", "theme": "夏キャンペーン", "text": "夏の特別キャンペーン。" * 25},
        ]
        p1, p2 = self._patch(posts)
        with p1, p2:
            results = run_content_check(_STORE, last_n=2)
        assert len(results[0]["posts"]) == 2
        assert results[0]["has_concerns"] is False

    def test_last_n_limits_posts(self):
        posts = [
            {"date": f"2026-08-0{i}", "theme": "テスト", "text": "テスト。" * 40}
            for i in range(1, 6)
        ]
        p1, p2 = self._patch(posts)
        with p1, p2:
            results = run_content_check(_STORE, last_n=3)
        assert len(results[0]["posts"]) == 3

    def test_multiple_stores(self):
        stores = [
            {"key": "store_a", "name": "店A", "industry": "beauty_salon"},
            {"key": "store_b", "name": "店B", "industry": "fitness_studio"},
        ]
        p1, p2 = self._patch([])
        with p1, p2:
            results = run_content_check(stores)
        assert len(results) == 2
        assert results[0]["store_key"] == "store_a"
        assert results[1]["store_key"] == "store_b"

    def test_has_concerns_true_on_low_jp_ratio(self):
        posts = [{"date": "2026-08-01", "theme": "test", "text": "all english text here " * 10}]
        p1, p2 = self._patch(posts)
        with p1, p2:
            results = run_content_check(_STORE)
        assert results[0]["has_concerns"] is True

    def test_has_concerns_true_on_repeated_opening(self):
        opening = "今月のキャンペーン情報をお届けします。"
        posts = [
            {"date": "2026-08-01", "theme": "A", "text": opening + "内容A。" * 40},
            {"date": "2026-07-31", "theme": "B", "text": opening + "内容B。" * 40},
        ]
        p1, p2 = self._patch(posts)
        with p1, p2:
            results = run_content_check(_STORE)
        assert results[0]["has_concerns"] is True
        assert len(results[0]["repeated_openings"]) == 1

    def test_result_includes_max_post_chars(self):
        p1, p2 = self._patch([], defaults={"max_post_chars": 300})
        with p1, p2:
            results = run_content_check(_STORE)
        assert results[0]["max_post_chars"] == 300


# ---------------------------------------------------------------------------
# _format_output
# ---------------------------------------------------------------------------

def _make_result(posts=None, repeated=None, has_concerns=False):
    return {
        "store_key": "test_store",
        "name": "テスト店",
        "max_post_chars": 500,
        "posts": posts or [],
        "repeated_openings": repeated or [],
        "has_concerns": has_concerns,
    }


class TestFormatOutput:
    def test_no_posts_shows_placeholder(self):
        output = _format_output([_make_result()], last_n=3)
        assert "投稿履歴なし" in output

    def test_with_post_shows_full_text(self):
        full_text = "秋のお手入れについてご案内します。" * 5
        result = _make_result(posts=[{
            "date": "2026-08-01",
            "theme": "秋",
            "text": full_text,
            "char_count": len(full_text),
            "jp_ratio": 0.95,
            "concerns": [],
        }])
        output = _format_output([result], last_n=3)
        assert "秋のお手入れ" in output

    def test_clean_post_shows_checkmark(self):
        result = _make_result(posts=[{
            "date": "2026-08-01", "theme": "テスト",
            "text": "テスト" * 50, "char_count": 150,
            "jp_ratio": 1.0, "concerns": [],
        }])
        output = _format_output([result], last_n=3)
        assert "✓" in output

    def test_concern_shows_warning_symbol(self):
        result = _make_result(
            has_concerns=True,
            posts=[{
                "date": "2026-08-01", "theme": "test",
                "text": "short", "char_count": 5,
                "jp_ratio": 0.0,
                "concerns": ["日本語率が低い (0%; 目標: 80% 以上)"],
            }],
        )
        output = _format_output([result], last_n=3)
        assert "⚠" in output
        assert "日本語率" in output

    def test_repeated_opening_in_output(self):
        result = _make_result(
            has_concerns=True,
            posts=[
                {
                    "date": "2026-08-01", "theme": "A",
                    "text": "同じ書き出しの投稿A。" * 20,
                    "char_count": 200, "jp_ratio": 0.9, "concerns": [],
                },
                {
                    "date": "2026-07-31", "theme": "B",
                    "text": "同じ書き出しの投稿B。" * 20,
                    "char_count": 200, "jp_ratio": 0.9, "concerns": [],
                },
            ],
            repeated=[(0, 1)],
        )
        output = _format_output([result], last_n=3)
        assert "書き出しが同じ" in output
        assert "[1]" in output
        assert "[2]" in output

    def test_overall_ok_message_when_no_concerns(self):
        output = _format_output([_make_result()], last_n=3)
        assert "問題なし" in output

    def test_overall_warn_message_when_concerns_exist(self):
        result = _make_result(has_concerns=True, repeated=[(0, 1)])
        output = _format_output([result], last_n=3)
        assert "確認が必要" in output

    def test_last_n_shown_in_header(self):
        output = _format_output([_make_result()], last_n=7)
        assert "7" in output

    def test_multiline_post_text_rendered(self):
        multiline = "一行目です。\n二行目です。\n三行目です。"
        result = _make_result(posts=[{
            "date": "2026-08-01", "theme": "テスト",
            "text": multiline, "char_count": len(multiline),
            "jp_ratio": 0.9, "concerns": [],
        }])
        output = _format_output([result], last_n=3)
        assert "一行目" in output
        assert "二行目" in output
        assert "三行目" in output


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

_ALL_STORES = [
    {
        "key": "the_body_kyoto",
        "name": "THE BODY 京都店",
        "industry": "beauty_salon",
        "location_id": "loc1",
        "drive_folder_id": "drv1",
    }
]

_CLEAN_POSTS = [
    {"date": "2026-08-01", "theme": "秋のケア", "text": "テスト投稿です。" * 30}
]

_BAD_POSTS = [
    {"date": "2026-08-01", "theme": "test", "text": "english only text here " * 10}
]


class TestMain:
    def _base_patches(self, posts, defaults=None):
        return [
            patch("meo.tools.content_check.cfg.store_list", return_value=_ALL_STORES),
            patch("meo.tools.content_check.get_post_history", return_value=posts),
            patch(
                "meo.tools.content_check.cfg.effective_defaults",
                return_value=defaults or _DEFAULTS,
            ),
        ]

    def test_exits_0_when_no_concerns(self, capsys):
        patches = self._base_patches(_CLEAN_POSTS)
        with patches[0], patches[1], patches[2]:
            with pytest.raises(SystemExit) as exc:
                sys.argv = ["meo-content-check"]
                main()
        assert exc.value.code == 0

    def test_exits_1_when_concern_detected(self, capsys):
        patches = self._base_patches(_BAD_POSTS)
        with patches[0], patches[1], patches[2]:
            with pytest.raises(SystemExit) as exc:
                sys.argv = ["meo-content-check"]
                main()
        assert exc.value.code == 1

    def test_store_filter_limits_to_one_store(self):
        with patch("meo.tools.content_check.cfg.store_list", return_value=_ALL_STORES):
            with patch("meo.tools.content_check.get_post_history", return_value=[]) as mock_hist:
                with patch("meo.tools.content_check.cfg.effective_defaults", return_value=_DEFAULTS):
                    with pytest.raises(SystemExit):
                        sys.argv = ["meo-content-check", "--store", "the_body_kyoto"]
                        main()
        assert mock_hist.call_count == 1

    def test_unknown_store_exits_1(self, capsys):
        with patch("meo.tools.content_check.cfg.store_list", return_value=_ALL_STORES):
            with pytest.raises(SystemExit) as exc:
                sys.argv = ["meo-content-check", "--store", "no_such_store"]
                main()
        assert exc.value.code == 1

    def test_json_output_is_valid_json(self, capsys):
        patches = self._base_patches([])
        with patches[0], patches[1], patches[2]:
            with pytest.raises(SystemExit):
                sys.argv = ["meo-content-check", "--json"]
                main()
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["store_key"] == "the_body_kyoto"

    def test_last_flag_limits_posts_in_output(self, capsys):
        many_posts = [
            {"date": f"2026-08-{i:02d}", "theme": "テスト", "text": "テスト投稿。" * 40}
            for i in range(1, 6)
        ]
        patches = self._base_patches(many_posts)
        with patches[0], patches[1], patches[2]:
            with pytest.raises(SystemExit):
                sys.argv = ["meo-content-check", "--last", "2"]
                main()
        out = capsys.readouterr().out
        assert "[1]" in out
        assert "[2]" in out
        assert "[3]" not in out

    def test_json_output_includes_concerns(self, capsys):
        patches = self._base_patches(_BAD_POSTS)
        with patches[0], patches[1], patches[2]:
            with pytest.raises(SystemExit):
                sys.argv = ["meo-content-check", "--json"]
                main()
        data = json.loads(capsys.readouterr().out)
        assert data[0]["has_concerns"] is True
        assert data[0]["posts"][0]["concerns"]

    def test_formatted_output_contains_store_name(self, capsys):
        patches = self._base_patches([])
        with patches[0], patches[1], patches[2]:
            with pytest.raises(SystemExit):
                sys.argv = ["meo-content-check"]
                main()
        out = capsys.readouterr().out
        assert "THE BODY 京都店" in out

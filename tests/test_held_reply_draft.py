"""Tests for meo.tools.held_reply_draft."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from meo.tools.held_reply_draft import (
    _format_output,
    _held_to_review_resource,
    _star_symbol,
    main,
    run_held_reply_draft,
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
        "comment": "期待していたほどではありませんでした。",
        "review_date": "2026-07-25",
        "date": "2026-07-31",
    },
    {
        "review_id": "rev_002",
        "reviewer": "佐藤様",
        "stars": "TWO",
        "comment": "少し待ち時間が長かったです。",
        "review_date": "2026-07-26",
        "date": "2026-07-31",
    },
]

_HELD_KYOTO = [
    {
        "review_id": "rev_003",
        "reviewer": "鈴木様",
        "stars": "TWO",
        "comment": "サービスがいまいちでした。",
        "review_date": "2026-07-27",
        "date": "2026-07-31",
    },
]


@pytest.fixture(autouse=True)
def _patch_stores(monkeypatch):
    monkeypatch.setattr("meo.tools.held_reply_draft.cfg.store_list", lambda: list(_STORES))


@pytest.fixture(autouse=True)
def _no_held_reviews(monkeypatch):
    monkeypatch.setattr("meo.tools.held_reply_draft.get_held_reviews", lambda key: [])


# ---------------------------------------------------------------------------
# _star_symbol
# ---------------------------------------------------------------------------

def test_star_symbol_five():
    assert _star_symbol("FIVE") == "★★★★★"


def test_star_symbol_one():
    assert _star_symbol("ONE") == "★☆☆☆☆"


def test_star_symbol_three():
    assert _star_symbol("THREE") == "★★★☆☆"


def test_star_symbol_unknown_returns_raw():
    assert _star_symbol("UNKNOWN") == "UNKNOWN"


def test_star_symbol_empty_returns_fallback():
    assert _star_symbol("") == "？"


def test_star_symbol_case_insensitive():
    assert _star_symbol("four") == "★★★★☆"


# ---------------------------------------------------------------------------
# _held_to_review_resource
# ---------------------------------------------------------------------------

def test_held_to_review_resource_reviewer_becomes_display_name():
    held = {"reviewer": "田中様", "stars": "ONE", "comment": "bad", "review_id": "r1"}
    resource = _held_to_review_resource(held)
    assert resource["reviewer"]["displayName"] == "田中様"


def test_held_to_review_resource_stars_becomes_star_rating():
    held = {"reviewer": "田中様", "stars": "TWO", "comment": "", "review_id": "r1"}
    resource = _held_to_review_resource(held)
    assert resource["starRating"] == "TWO"


def test_held_to_review_resource_comment_preserved():
    held = {"reviewer": "A", "stars": "ONE", "comment": "詳細", "review_id": "r1"}
    resource = _held_to_review_resource(held)
    assert resource["comment"] == "詳細"


def test_held_to_review_resource_review_id_becomes_review_id():
    held = {"reviewer": "A", "stars": "ONE", "comment": "", "review_id": "rev_abc"}
    resource = _held_to_review_resource(held)
    assert resource["reviewId"] == "rev_abc"


def test_held_to_review_resource_missing_reviewer_defaults_to_guest():
    held = {"stars": "ONE", "comment": "", "review_id": "r1"}
    resource = _held_to_review_resource(held)
    assert resource["reviewer"]["displayName"] == "お客様"


def test_held_to_review_resource_empty_reviewer_defaults_to_guest():
    held = {"reviewer": "", "stars": "ONE", "comment": "", "review_id": "r1"}
    resource = _held_to_review_resource(held)
    assert resource["reviewer"]["displayName"] == "お客様"


# ---------------------------------------------------------------------------
# run_held_reply_draft
# ---------------------------------------------------------------------------

def test_run_held_reply_draft_no_held_returns_empty(monkeypatch):
    result = run_held_reply_draft(_STORES)
    assert result == []


def test_run_held_reply_draft_one_store_has_held(monkeypatch):
    monkeypatch.setattr(
        "meo.tools.held_reply_draft.get_held_reviews",
        lambda key: _HELD_OSAKA if key == "the_body_osaka_shinsaibashi" else [],
    )
    with patch("meo.tools.held_reply_draft.generate_reply", return_value="田中様、ありがとうございます。"):
        result = run_held_reply_draft(_STORES)
    assert len(result) == 1
    assert result[0]["store_key"] == "the_body_osaka_shinsaibashi"


def test_run_held_reply_draft_draft_count_matches_held(monkeypatch):
    monkeypatch.setattr(
        "meo.tools.held_reply_draft.get_held_reviews",
        lambda key: _HELD_OSAKA if key == "the_body_osaka_shinsaibashi" else [],
    )
    with patch("meo.tools.held_reply_draft.generate_reply", return_value="返信文"):
        result = run_held_reply_draft(_STORES)
    assert len(result[0]["drafts"]) == 2


def test_run_held_reply_draft_draft_text_captured(monkeypatch):
    monkeypatch.setattr(
        "meo.tools.held_reply_draft.get_held_reviews",
        lambda key: _HELD_OSAKA[:1] if key == "the_body_osaka_shinsaibashi" else [],
    )
    with patch("meo.tools.held_reply_draft.generate_reply", return_value="生成された返信テキスト"):
        result = run_held_reply_draft(_STORES)
    assert result[0]["drafts"][0]["draft"] == "生成された返信テキスト"
    assert result[0]["drafts"][0]["error"] is None


def test_run_held_reply_draft_llm_error_captured(monkeypatch):
    monkeypatch.setattr(
        "meo.tools.held_reply_draft.get_held_reviews",
        lambda key: _HELD_OSAKA[:1] if key == "the_body_osaka_shinsaibashi" else [],
    )
    with patch("meo.tools.held_reply_draft.generate_reply", side_effect=RuntimeError("API error")):
        result = run_held_reply_draft(_STORES)
    d = result[0]["drafts"][0]
    assert d["error"] == "API error"
    assert d["draft"] == ""


def test_run_held_reply_draft_store_without_held_omitted(monkeypatch):
    monkeypatch.setattr(
        "meo.tools.held_reply_draft.get_held_reviews",
        lambda key: _HELD_KYOTO if key == "the_body_kyoto" else [],
    )
    with patch("meo.tools.held_reply_draft.generate_reply", return_value="返信"):
        result = run_held_reply_draft(_STORES)
    keys = [r["store_key"] for r in result]
    assert "the_body_kyoto" in keys
    assert "the_body_osaka_shinsaibashi" not in keys
    assert "mybear_studio_kyoto" not in keys


def test_run_held_reply_draft_multiple_stores_included(monkeypatch):
    def _held(key):
        if key == "the_body_osaka_shinsaibashi":
            return _HELD_OSAKA
        if key == "the_body_kyoto":
            return _HELD_KYOTO
        return []
    monkeypatch.setattr("meo.tools.held_reply_draft.get_held_reviews", _held)
    with patch("meo.tools.held_reply_draft.generate_reply", return_value="返信"):
        result = run_held_reply_draft(_STORES)
    assert len(result) == 2


def test_run_held_reply_draft_held_entry_preserved_in_result(monkeypatch):
    monkeypatch.setattr(
        "meo.tools.held_reply_draft.get_held_reviews",
        lambda key: _HELD_OSAKA[:1] if key == "the_body_osaka_shinsaibashi" else [],
    )
    with patch("meo.tools.held_reply_draft.generate_reply", return_value="返信"):
        result = run_held_reply_draft(_STORES)
    assert result[0]["drafts"][0]["held"] == _HELD_OSAKA[0]


def test_run_held_reply_draft_store_name_in_result(monkeypatch):
    monkeypatch.setattr(
        "meo.tools.held_reply_draft.get_held_reviews",
        lambda key: _HELD_OSAKA[:1] if key == "the_body_osaka_shinsaibashi" else [],
    )
    with patch("meo.tools.held_reply_draft.generate_reply", return_value="返信"):
        result = run_held_reply_draft(_STORES)
    assert result[0]["store_name"] == "THE BODY 大阪 心斎橋店"


def test_run_held_reply_draft_errors_do_not_stop_other_entries(monkeypatch):
    monkeypatch.setattr(
        "meo.tools.held_reply_draft.get_held_reviews",
        lambda key: _HELD_OSAKA if key == "the_body_osaka_shinsaibashi" else [],
    )
    call_count = 0

    def _gen(review, store):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("first fails")
        return "second OK"

    with patch("meo.tools.held_reply_draft.generate_reply", side_effect=_gen):
        result = run_held_reply_draft(_STORES)
    drafts = result[0]["drafts"]
    assert drafts[0]["error"] == "first fails"
    assert drafts[1]["draft"] == "second OK"
    assert drafts[1]["error"] is None


# ---------------------------------------------------------------------------
# _format_output
# ---------------------------------------------------------------------------

def _make_result(store_key: str, store_name: str, drafts: list[dict]) -> dict:
    return {"store_key": store_key, "store_name": store_name, "drafts": drafts}


def _make_draft(held: dict, draft: str = "返信ドラフト", error: str | None = None) -> dict:
    return {"held": held, "draft": draft, "error": error}


def test_format_output_empty_results():
    output = _format_output([])
    assert "保留中のレビューはありません" in output


def test_format_output_contains_header():
    output = _format_output([])
    assert "MEO Automation — 保留中レビューへの返信ドラフト" in output


def test_format_output_contains_timestamp():
    output = _format_output([])
    assert "Generated:" in output
    assert "JST" in output


def test_format_output_store_name_present():
    held = _HELD_OSAKA[0]
    r = _make_result("the_body_osaka_shinsaibashi", "THE BODY 大阪 心斎橋店", [_make_draft(held)])
    output = _format_output([r])
    assert "THE BODY 大阪 心斎橋店" in output


def test_format_output_store_key_present():
    held = _HELD_OSAKA[0]
    r = _make_result("the_body_osaka_shinsaibashi", "THE BODY 大阪 心斎橋店", [_make_draft(held)])
    output = _format_output([r])
    assert "the_body_osaka_shinsaibashi" in output


def test_format_output_reviewer_name_present():
    held = _HELD_OSAKA[0]
    r = _make_result("the_body_osaka_shinsaibashi", "THE BODY 大阪 心斎橋店", [_make_draft(held)])
    output = _format_output([r])
    assert "田中様" in output


def test_format_output_star_symbol_present():
    held = _HELD_OSAKA[0]  # stars: ONE
    r = _make_result("the_body_osaka_shinsaibashi", "THE BODY 大阪 心斎橋店", [_make_draft(held)])
    output = _format_output([r])
    assert "★☆☆☆☆" in output


def test_format_output_review_date_present():
    held = _HELD_OSAKA[0]  # review_date: 2026-07-25
    r = _make_result("the_body_osaka_shinsaibashi", "THE BODY 大阪 心斎橋店", [_make_draft(held)])
    output = _format_output([r])
    assert "2026-07-25" in output


def test_format_output_comment_present():
    held = _HELD_OSAKA[0]
    r = _make_result("the_body_osaka_shinsaibashi", "THE BODY 大阪 心斎橋店", [_make_draft(held)])
    output = _format_output([r])
    assert "期待していたほどではありませんでした" in output


def test_format_output_draft_text_present():
    held = _HELD_OSAKA[0]
    r = _make_result("the_body_osaka_shinsaibashi", "THE BODY 大阪 心斎橋店",
                     [_make_draft(held, draft="ありがとうございます")])
    output = _format_output([r])
    assert "ありがとうございます" in output


def test_format_output_error_shown_when_draft_failed():
    held = _HELD_OSAKA[0]
    r = _make_result("the_body_osaka_shinsaibashi", "THE BODY 大阪 心斎橋店",
                     [_make_draft(held, draft="", error="API timeout")])
    output = _format_output([r])
    assert "ERROR: API timeout" in output


def test_format_output_total_count_in_footer():
    held1, held2 = _HELD_OSAKA
    r = _make_result("the_body_osaka_shinsaibashi", "THE BODY 大阪 心斎橋店",
                     [_make_draft(held1), _make_draft(held2)])
    output = _format_output([r])
    assert "2件のドラフト" in output


def test_format_output_no_comment_shows_placeholder():
    held = {**_HELD_OSAKA[0], "comment": ""}
    r = _make_result("the_body_osaka_shinsaibashi", "THE BODY 大阪 心斎橋店", [_make_draft(held)])
    output = _format_output([r])
    assert "コメントなし" in output


def test_format_output_review_date_fallback_to_date_field():
    held = {
        "review_id": "r1",
        "reviewer": "A",
        "stars": "ONE",
        "comment": "",
        "date": "2026-07-31",
        # review_date intentionally absent
    }
    r = _make_result("the_body_osaka_shinsaibashi", "THE BODY 大阪 心斎橋店", [_make_draft(held)])
    output = _format_output([r])
    assert "2026-07-31" in output


def test_format_output_anonymous_reviewer_shown():
    held = {**_HELD_OSAKA[0], "reviewer": ""}
    r = _make_result("the_body_osaka_shinsaibashi", "THE BODY 大阪 心斎橋店", [_make_draft(held)])
    output = _format_output([r])
    assert "匿名" in output


def test_format_output_index_counter_shown():
    held1, held2 = _HELD_OSAKA
    r = _make_result("the_body_osaka_shinsaibashi", "THE BODY 大阪 心斎橋店",
                     [_make_draft(held1), _make_draft(held2)])
    output = _format_output([r])
    assert "[1/2]" in output
    assert "[2/2]" in output


def test_format_output_draft_arrow_marker():
    held = _HELD_OSAKA[0]
    r = _make_result("the_body_osaka_shinsaibashi", "THE BODY 大阪 心斎橋店", [_make_draft(held)])
    output = _format_output([r])
    assert "▶ 返信ドラフト" in output


def test_format_output_count_in_store_header():
    held1, held2 = _HELD_OSAKA
    r = _make_result("the_body_osaka_shinsaibashi", "THE BODY 大阪 心斎橋店",
                     [_make_draft(held1), _make_draft(held2)])
    output = _format_output([r])
    assert "2件" in output


def test_format_output_multiline_draft_preserved():
    held = _HELD_OSAKA[0]
    draft_text = "行1\n行2\n行3"
    r = _make_result("the_body_osaka_shinsaibashi", "THE BODY 大阪 心斎橋店",
                     [_make_draft(held, draft=draft_text)])
    output = _format_output([r])
    assert "行1" in output
    assert "行2" in output
    assert "行3" in output


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def test_main_no_held_reviews_exits_0(monkeypatch, capsys):
    with patch("sys.argv", ["meo-held-reply-draft"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "保留中のレビューはありません" in captured.err


def test_main_with_held_exits_0(monkeypatch, capsys):
    monkeypatch.setattr(
        "meo.tools.held_reply_draft.get_held_reviews",
        lambda key: _HELD_OSAKA if key == "the_body_osaka_shinsaibashi" else [],
    )
    with patch("sys.argv", ["meo-held-reply-draft"]):
        with patch("meo.tools.held_reply_draft.generate_reply", return_value="返信OK"):
            with pytest.raises(SystemExit) as exc_info:
                main()
    assert exc_info.value.code == 0


def test_main_output_printed_to_stdout(monkeypatch, capsys):
    monkeypatch.setattr(
        "meo.tools.held_reply_draft.get_held_reviews",
        lambda key: _HELD_OSAKA[:1] if key == "the_body_osaka_shinsaibashi" else [],
    )
    with patch("sys.argv", ["meo-held-reply-draft"]):
        with patch("meo.tools.held_reply_draft.generate_reply", return_value="返信OK"):
            with pytest.raises(SystemExit):
                main()
    captured = capsys.readouterr()
    assert "THE BODY 大阪 心斎橋店" in captured.out


def test_main_llm_error_exits_1(monkeypatch, capsys):
    monkeypatch.setattr(
        "meo.tools.held_reply_draft.get_held_reviews",
        lambda key: _HELD_OSAKA[:1] if key == "the_body_osaka_shinsaibashi" else [],
    )
    with patch("sys.argv", ["meo-held-reply-draft"]):
        with patch("meo.tools.held_reply_draft.generate_reply", side_effect=RuntimeError("LLM fail")):
            with pytest.raises(SystemExit) as exc_info:
                main()
    assert exc_info.value.code == 1


def test_main_unknown_store_exits_1(monkeypatch, capsys):
    with patch("sys.argv", ["meo-held-reply-draft", "--store", "unknown_key"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Unknown store key" in captured.err


def test_main_store_filter_limits_output(monkeypatch, capsys):
    def _held(key):
        if key == "the_body_osaka_shinsaibashi":
            return _HELD_OSAKA
        if key == "the_body_kyoto":
            return _HELD_KYOTO
        return []
    monkeypatch.setattr("meo.tools.held_reply_draft.get_held_reviews", _held)
    with patch("sys.argv", ["meo-held-reply-draft", "--store", "the_body_kyoto"]):
        with patch("meo.tools.held_reply_draft.generate_reply", return_value="返信"):
            with pytest.raises(SystemExit) as exc_info:
                main()
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "THE BODY 京都店" in captured.out
    assert "THE BODY 大阪 心斎橋店" not in captured.out


def test_main_output_file_saves_content(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        "meo.tools.held_reply_draft.get_held_reviews",
        lambda key: _HELD_OSAKA[:1] if key == "the_body_osaka_shinsaibashi" else [],
    )
    out_file = tmp_path / "drafts.txt"
    with patch("sys.argv", ["meo-held-reply-draft", "--output", str(out_file)]):
        with patch("meo.tools.held_reply_draft.generate_reply", return_value="返信テキスト"):
            with pytest.raises(SystemExit):
                main()
    content = out_file.read_text(encoding="utf-8")
    assert "返信テキスト" in content

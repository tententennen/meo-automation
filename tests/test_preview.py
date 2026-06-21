"""Tests for the meo-preview CLI tool (tools/preview.py)."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from meo.tools import preview as prev_mod
from meo.tools.preview import _format_output, run_preview

_STORES = [
    {"key": "the_body_kyoto", "name": "THE BODY 京都店", "industry": "beauty_salon"},
    {"key": "mybear_studio_kyoto", "name": "MYBEAR STUDIO 京都店", "industry": "fitness_studio"},
]


# ---------------------------------------------------------------------------
# run_preview()
# ---------------------------------------------------------------------------

def test_run_preview_returns_post_and_reply_for_each_store():
    with (
        patch("meo.tools.preview.generate_post", return_value="投稿テキスト"),
        patch("meo.tools.preview.generate_reply", return_value="返信テキスト"),
    ):
        results = run_preview(_STORES)
    assert len(results) == 2
    for r in results:
        assert r["post"] == "投稿テキスト"
        assert r["reply"] == "返信テキスト"
        assert "post_error" not in r
        assert "reply_error" not in r


def test_run_preview_captures_post_error():
    with (
        patch("meo.tools.preview.generate_post", side_effect=RuntimeError("API error")),
        patch("meo.tools.preview.generate_reply", return_value="返信テキスト"),
    ):
        results = run_preview(_STORES[:1])
    r = results[0]
    assert "post" not in r
    assert "post_error" in r
    assert "API error" in r["post_error"]


def test_run_preview_captures_reply_error():
    with (
        patch("meo.tools.preview.generate_post", return_value="投稿テキスト"),
        patch("meo.tools.preview.generate_reply", side_effect=RuntimeError("LLM error")),
    ):
        results = run_preview(_STORES[:1])
    r = results[0]
    assert "reply" not in r
    assert "reply_error" in r
    assert "LLM error" in r["reply_error"]


def test_run_preview_continues_after_one_store_error():
    """An error in one store must not prevent other stores from being processed."""
    def maybe_fail(store, **kw):
        if store["key"] == "the_body_kyoto":
            raise RuntimeError("first store fail")
        return "投稿"

    with (
        patch("meo.tools.preview.generate_post", side_effect=maybe_fail),
        patch("meo.tools.preview.generate_reply", return_value="返信"),
    ):
        results = run_preview(_STORES)
    assert len(results) == 2
    assert "post_error" in results[0]
    assert results[1]["post"] == "投稿"


# ---------------------------------------------------------------------------
# _format_output()
# ---------------------------------------------------------------------------

def test_format_output_contains_store_name_and_content():
    results = [{"store_key": "k", "name": "テスト店", "post": "投稿文", "reply": "返信文"}]
    out = _format_output(results)
    assert "テスト店" in out
    assert "投稿文" in out
    assert "返信文" in out


def test_format_output_marks_errors():
    results = [{"store_key": "k", "name": "テスト店", "post_error": "API key missing", "reply": "返信"}]
    out = _format_output(results)
    assert "ERROR" in out
    assert "API key missing" in out


def test_format_output_marks_reply_error():
    """_format_output() renders reply_error (no 'reply' key) as ERROR line."""
    results = [{"store_key": "k", "name": "テスト店", "post": "投稿文", "reply_error": "Rate limit"}]
    out = _format_output(results)
    assert "ERROR" in out
    assert "Rate limit" in out


def test_format_output_contains_timestamp():
    results = [{"store_key": "k", "name": "N", "post": "P", "reply": "R"}]
    out = _format_output(results)
    assert "JST" in out


# ---------------------------------------------------------------------------
# main() CLI
# ---------------------------------------------------------------------------

def test_main_exits_0_on_success(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["meo-preview"])
    with (
        patch("meo.tools.preview.generate_post", return_value="投稿"),
        patch("meo.tools.preview.generate_reply", return_value="返信"),
    ):
        with pytest.raises(SystemExit) as exc_info:
            prev_mod.main()
    assert exc_info.value.code == 0


def test_main_exits_1_when_any_store_has_error(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["meo-preview"])
    with (
        patch("meo.tools.preview.generate_post", side_effect=RuntimeError("fail")),
        patch("meo.tools.preview.generate_reply", return_value="返信"),
    ):
        with pytest.raises(SystemExit) as exc_info:
            prev_mod.main()
    assert exc_info.value.code == 1


def test_main_store_filter_limits_to_one_store(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["meo-preview", "--store", "the_body_kyoto"])
    generated_for: list[str] = []

    def capture(store, **kw):
        generated_for.append(store["key"])
        return "投稿"

    with (
        patch("meo.tools.preview.generate_post", side_effect=capture),
        patch("meo.tools.preview.generate_reply", return_value="返信"),
    ):
        with pytest.raises(SystemExit):
            prev_mod.main()

    assert generated_for == ["the_body_kyoto"]


def test_main_unknown_store_exits_1(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["meo-preview", "--store", "nonexistent_store"])
    with pytest.raises(SystemExit) as exc_info:
        prev_mod.main()
    assert exc_info.value.code == 1


def test_main_output_flag_saves_file(tmp_path, monkeypatch):
    out_file = tmp_path / "preview.txt"
    monkeypatch.setattr(sys, "argv", ["meo-preview", "--output", str(out_file)])
    with (
        patch("meo.tools.preview.generate_post", return_value="投稿テキスト"),
        patch("meo.tools.preview.generate_reply", return_value="返信テキスト"),
    ):
        with pytest.raises(SystemExit):
            prev_mod.main()

    assert out_file.exists()
    saved = out_file.read_text(encoding="utf-8")
    assert "投稿テキスト" in saved
    assert "返信テキスト" in saved

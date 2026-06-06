"""Tests for meo.tools.export — CSV export of post/reply history."""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures / constants
# ---------------------------------------------------------------------------

_STORES = [
    {"key": "the_body_kyoto", "name": "THE BODY 京都店", "industry": "beauty_salon"},
    {"key": "mybear_studio_kyoto", "name": "MYBEAR STUDIO 京都店", "industry": "fitness_studio"},
]

_POST_HISTORY_KYOTO = [
    {
        "date": "2026-01-10",
        "theme": "季節のお手入れ情報",
        "text": "冬の乾燥対策に。。。",
        "post_name": "accounts/123/locations/456/localPosts/789",
    },
    {
        "date": "2026-01-09",
        "theme": "キャンペーン・お得情報",
        "text": "新年キャンペーン実施中！",
        "post_name": "",
    },
]

_REPLY_HISTORY_KYOTO = [
    {
        "date": "2026-01-10",
        "review_id": "rev001",
        "reviewer": "田中様",
        "stars": "FIVE",
        "reply": "ご来店ありがとうございます！",
    },
    {
        "date": "2026-01-09",
        "review_id": "rev002",
        "reviewer": "匿名",
        "stars": "THREE",
        "reply": "ご意見ありがとうございます。",
    },
]


@pytest.fixture(autouse=True)
def _patch_store_list(monkeypatch):
    monkeypatch.setattr("meo.tools.export.cfg.store_list", lambda: list(_STORES))


@pytest.fixture()
def _patch_post_history(monkeypatch):
    def _hist(store_key):
        return list(_POST_HISTORY_KYOTO) if store_key == "the_body_kyoto" else []
    monkeypatch.setattr("meo.tools.export.state.get_post_history", _hist)


@pytest.fixture()
def _patch_reply_history(monkeypatch):
    def _hist(store_key):
        return list(_REPLY_HISTORY_KYOTO) if store_key == "the_body_kyoto" else []
    monkeypatch.setattr("meo.tools.export.state.get_reply_history", _hist)


@pytest.fixture()
def _no_history(monkeypatch):
    monkeypatch.setattr("meo.tools.export.state.get_post_history", lambda k: [])
    monkeypatch.setattr("meo.tools.export.state.get_reply_history", lambda k: [])


# ---------------------------------------------------------------------------
# export_posts()
# ---------------------------------------------------------------------------

class TestExportPosts:
    def test_returns_one_row_per_entry(self, _patch_post_history):
        from meo.tools.export import export_posts
        rows = export_posts(_STORES)
        assert len(rows) == 2  # 2 entries for kyoto; 0 for mybear

    def test_row_includes_required_fields(self, _patch_post_history):
        from meo.tools.export import export_posts
        row = export_posts(_STORES)[0]
        assert row["store_key"] == "the_body_kyoto"
        assert row["store_name"] == "THE BODY 京都店"
        assert row["date"] == "2026-01-10"
        assert row["theme"] == "季節のお手入れ情報"
        assert "冬の乾燥" in row["text"]
        assert "localPosts/789" in row["post_name"]

    def test_ordering_matches_history(self, _patch_post_history):
        from meo.tools.export import export_posts
        rows = export_posts(_STORES)
        assert rows[0]["date"] == "2026-01-10"
        assert rows[1]["date"] == "2026-01-09"

    def test_empty_store_contributes_no_rows(self, _patch_post_history):
        from meo.tools.export import export_posts
        rows = export_posts([s for s in _STORES if s["key"] == "mybear_studio_kyoto"])
        assert rows == []

    def test_all_stores_combined(self, _patch_post_history):
        from meo.tools.export import export_posts
        rows = export_posts(_STORES)
        keys = {r["store_key"] for r in rows}
        assert keys == {"the_body_kyoto"}  # mybear has no history in fixture


# ---------------------------------------------------------------------------
# export_replies()
# ---------------------------------------------------------------------------

class TestExportReplies:
    def test_returns_one_row_per_entry(self, _patch_reply_history):
        from meo.tools.export import export_replies
        rows = export_replies(_STORES)
        assert len(rows) == 2

    def test_row_includes_required_fields(self, _patch_reply_history):
        from meo.tools.export import export_replies
        row = export_replies(_STORES)[0]
        assert row["reviewer"] == "田中様"
        assert row["stars"] == "FIVE"
        assert row["review_id"] == "rev001"
        assert "ありがとう" in row["reply"]

    def test_empty_store_contributes_no_rows(self, _patch_reply_history):
        from meo.tools.export import export_replies
        rows = export_replies([s for s in _STORES if s["key"] == "mybear_studio_kyoto"])
        assert rows == []


# ---------------------------------------------------------------------------
# _write_csv()
# ---------------------------------------------------------------------------

class TestWriteCsv:
    def test_stdout_contains_header_and_data(self, capsys):
        from meo.tools.export import _write_csv
        rows = [{"a": "hello", "b": "world"}]
        _write_csv(rows, ["a", "b"], output=None)
        out = capsys.readouterr().out
        assert "a,b" in out
        assert "hello,world" in out

    def test_file_written_with_bom(self, tmp_path):
        from meo.tools.export import _write_csv
        out_path = tmp_path / "out.csv"
        rows = [{"x": "テスト", "y": "2026-01-01"}]
        _write_csv(rows, ["x", "y"], output=str(out_path))
        raw = out_path.read_bytes()
        assert raw[:3] == b"\xef\xbb\xbf", "Expected UTF-8 BOM for Excel compatibility"

    def test_file_contains_data(self, tmp_path):
        from meo.tools.export import _write_csv
        out_path = tmp_path / "out.csv"
        rows = [{"col": "value"}]
        _write_csv(rows, ["col"], output=str(out_path))
        content = out_path.read_text(encoding="utf-8-sig")
        assert "col" in content
        assert "value" in content

    def test_stderr_reports_row_count(self, tmp_path, capsys):
        from meo.tools.export import _write_csv
        out_path = tmp_path / "out.csv"
        rows = [{"k": "v1"}, {"k": "v2"}]
        _write_csv(rows, ["k"], output=str(out_path))
        err = capsys.readouterr().err
        assert "2" in err


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

class TestMain:
    def _run(self, argv, monkeypatch):
        monkeypatch.setattr(sys, "argv", argv)
        from meo.tools import export as export_mod
        import importlib
        importlib.reload(export_mod)
        from meo.tools.export import main
        main()

    def test_posts_prints_csv_header(self, capsys, _patch_post_history, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["meo-export", "posts"])
        from meo.tools.export import main
        main()
        out = capsys.readouterr().out
        assert "date" in out
        assert "theme" in out
        assert "text" in out

    def test_replies_prints_csv_header(self, capsys, _patch_reply_history, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["meo-export", "replies"])
        from meo.tools.export import main
        main()
        out = capsys.readouterr().out
        assert "reviewer" in out
        assert "stars" in out
        assert "reply" in out

    def test_posts_content_in_output(self, capsys, _patch_post_history, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["meo-export", "posts"])
        from meo.tools.export import main
        main()
        out = capsys.readouterr().out
        assert "the_body_kyoto" in out
        assert "2026-01-10" in out

    def test_store_filter_limits_to_one_store(self, capsys, _patch_post_history, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["meo-export", "posts", "--store", "the_body_kyoto"])
        from meo.tools.export import main
        main()
        out = capsys.readouterr().out
        assert "the_body_kyoto" in out

    def test_unknown_store_exits_1(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["meo-export", "posts", "--store", "nonexistent_key"])
        from meo.tools.export import main
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_no_history_exits_0(self, capsys, _no_history, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["meo-export", "posts"])
        from meo.tools.export import main
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
        err = capsys.readouterr().err
        assert "No data" in err

    def test_output_file_created(self, tmp_path, _patch_post_history, monkeypatch):
        out_path = tmp_path / "posts.csv"
        monkeypatch.setattr(sys, "argv", ["meo-export", "posts", "--output", str(out_path)])
        from meo.tools.export import main
        main()
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8-sig")
        assert "date" in content
        assert "theme" in content

    def test_output_file_replies(self, tmp_path, _patch_reply_history, monkeypatch):
        out_path = tmp_path / "replies.csv"
        monkeypatch.setattr(sys, "argv", ["meo-export", "replies", "--output", str(out_path)])
        from meo.tools.export import main
        main()
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8-sig")
        assert "reviewer" in content

    def test_output_file_has_japanese_content(self, tmp_path, _patch_post_history, monkeypatch):
        out_path = tmp_path / "posts.csv"
        monkeypatch.setattr(sys, "argv", ["meo-export", "posts", "--output", str(out_path)])
        from meo.tools.export import main
        main()
        content = out_path.read_text(encoding="utf-8-sig")
        assert "THE BODY 京都店" in content

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

_HELD_REVIEWS_KYOTO = [
    {
        "date": "2026-01-10",
        "review_date": "2026-01-05",
        "review_id": "rev_low_1",
        "reviewer": "不満なお客様",
        "stars": "ONE",
        "comment": "最悪でした。",
    },
    {
        "date": "2026-01-10",
        "review_date": "2026-01-03",
        "review_id": "rev_low_2",
        "reviewer": "まあまあ",
        "stars": "TWO",
        "comment": "普通でした。",
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
def _patch_held_history(monkeypatch):
    def _hist(store_key):
        return list(_HELD_REVIEWS_KYOTO) if store_key == "the_body_kyoto" else []
    monkeypatch.setattr("meo.tools.export.state.get_held_reviews", _hist)


_SCORE_SNAPSHOTS = [
    {
        "date": "2026-08-04",
        "grades": {
            "the_body_kyoto": "A",
            "mybear_studio_kyoto": "D",
        },
    },
    {
        "date": "2026-08-03",
        "grades": {
            "the_body_kyoto": "B",
            "mybear_studio_kyoto": "C",
        },
    },
]


_ANSWER_HISTORY_KYOTO = [
    {
        "date": "2026-01-10",
        "question_id": "locations/456/questions/q001",
        "question": "駐車場はありますか？",
        "answer": "近隣にコインパーキングがございます。",
    },
    {
        "date": "2026-01-08",
        "question_id": "locations/456/questions/q002",
        "question": "予約は必要ですか？",
        "answer": "予約不要でご来店いただけます。",
    },
]


@pytest.fixture()
def _patch_answer_history(monkeypatch):
    def _hist(store_key):
        return list(_ANSWER_HISTORY_KYOTO) if store_key == "the_body_kyoto" else []
    monkeypatch.setattr("meo.tools.export.state.get_answer_history", _hist)


@pytest.fixture()
def _no_history(monkeypatch):
    monkeypatch.setattr("meo.tools.export.state.get_post_history", lambda k: [])
    monkeypatch.setattr("meo.tools.export.state.get_reply_history", lambda k: [])
    monkeypatch.setattr("meo.tools.export.state.get_answer_history", lambda k: [])
    monkeypatch.setattr("meo.tools.export.state.get_held_reviews", lambda k: [])
    monkeypatch.setattr("meo.tools.export.state.get_score_snapshots", lambda: [])


@pytest.fixture()
def _patch_score_snapshots(monkeypatch):
    monkeypatch.setattr(
        "meo.tools.export.state.get_score_snapshots",
        lambda: list(_SCORE_SNAPSHOTS),
    )


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

    def test_image_fields_included_when_present(self, monkeypatch):
        """image_id and image_name from the history entry appear in the CSV row."""
        from meo.tools.export import export_posts
        history_with_image = [
            {
                "date": "2026-01-10",
                "theme": "季節のお手入れ情報",
                "text": "写真付き投稿",
                "post_name": "accounts/123/localPosts/1",
                "image_id": "abc123",
                "image_name": "summer.jpg",
            }
        ]
        monkeypatch.setattr(
            "meo.tools.export.state.get_post_history",
            lambda k: history_with_image if k == "the_body_kyoto" else [],
        )
        rows = export_posts(_STORES)
        row = next(r for r in rows if r["store_key"] == "the_body_kyoto")
        assert row["image_id"] == "abc123"
        assert row["image_name"] == "summer.jpg"

    def test_image_fields_empty_string_when_absent(self, _patch_post_history):
        """History entries without image fields export as empty strings (backward compat)."""
        from meo.tools.export import export_posts
        rows = export_posts(_STORES)
        # _POST_HISTORY_KYOTO entries have no image_id / image_name
        for row in rows:
            assert row["image_id"] == ""
            assert row["image_name"] == ""


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

    def test_held_reviews_prints_csv_header(self, capsys, _patch_held_history, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["meo-export", "held-reviews"])
        from meo.tools.export import main
        main()
        out = capsys.readouterr().out
        assert "review_date" in out
        assert "review_id" in out
        assert "reviewer" in out
        assert "comment" in out

    def test_held_reviews_content_in_output(self, capsys, _patch_held_history, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["meo-export", "held-reviews"])
        from meo.tools.export import main
        main()
        out = capsys.readouterr().out
        assert "rev_low_1" in out
        assert "不満なお客様" in out
        assert "ONE" in out

    def test_no_held_reviews_exits_0_with_helpful_message(
        self, capsys, _no_history, monkeypatch
    ):
        monkeypatch.setattr(sys, "argv", ["meo-export", "held-reviews"])
        from meo.tools.export import main
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
        err = capsys.readouterr().err
        assert "min_star_autoreply" in err


# ---------------------------------------------------------------------------
# export_held_reviews()
# ---------------------------------------------------------------------------

class TestExportHeldReviews:
    def test_returns_one_row_per_entry(self, _patch_held_history):
        from meo.tools.export import export_held_reviews
        rows = export_held_reviews(_STORES)
        assert len(rows) == 2  # 2 held for kyoto; 0 for mybear

    def test_row_includes_required_fields(self, _patch_held_history):
        from meo.tools.export import export_held_reviews
        row = export_held_reviews(_STORES)[0]
        assert row["store_key"] == "the_body_kyoto"
        assert row["store_name"] == "THE BODY 京都店"
        assert row["date"] == "2026-01-10"
        assert row["review_date"] == "2026-01-05"
        assert row["review_id"] == "rev_low_1"
        assert row["reviewer"] == "不満なお客様"
        assert row["stars"] == "ONE"
        assert row["comment"] == "最悪でした。"

    def test_empty_store_contributes_no_rows(self, _patch_held_history):
        from meo.tools.export import export_held_reviews
        rows = export_held_reviews([s for s in _STORES if s["key"] == "mybear_studio_kyoto"])
        assert rows == []


# ---------------------------------------------------------------------------
# export_score_history()
# ---------------------------------------------------------------------------

class TestExportScoreHistory:
    def test_returns_one_row_per_date_per_store(self, _patch_score_snapshots):
        from meo.tools.export import export_score_history
        rows = export_score_history(_STORES)
        # 2 snapshots × 2 stores in _STORES = 4 rows
        assert len(rows) == 4

    def test_row_includes_required_fields(self, _patch_score_snapshots):
        from meo.tools.export import export_score_history
        row = export_score_history(_STORES)[0]
        assert "date" in row
        assert "store_key" in row
        assert "store_name" in row
        assert "grade" in row

    def test_newest_snapshot_first(self, _patch_score_snapshots):
        from meo.tools.export import export_score_history
        rows = export_score_history(_STORES)
        assert rows[0]["date"] == "2026-08-04"
        assert rows[2]["date"] == "2026-08-03"

    def test_store_key_and_name_populated(self, _patch_score_snapshots):
        from meo.tools.export import export_score_history
        rows = export_score_history(_STORES)
        row_kyoto = next(r for r in rows if r["store_key"] == "the_body_kyoto" and r["date"] == "2026-08-04")
        assert row_kyoto["store_name"] == "THE BODY 京都店"
        assert row_kyoto["grade"] == "A"

    def test_grade_from_snapshot(self, _patch_score_snapshots):
        from meo.tools.export import export_score_history
        rows = export_score_history(_STORES)
        row_mybear = next(r for r in rows if r["store_key"] == "mybear_studio_kyoto" and r["date"] == "2026-08-04")
        assert row_mybear["grade"] == "D"

    def test_missing_store_in_snapshot_yields_empty_grade(self, monkeypatch):
        from meo.tools.export import export_score_history
        # Snapshot has no entry for the_body_kyoto (store added after first snapshot)
        monkeypatch.setattr(
            "meo.tools.export.state.get_score_snapshots",
            lambda: [{"date": "2026-08-01", "grades": {"mybear_studio_kyoto": "B"}}],
        )
        rows = export_score_history(_STORES)
        row_kyoto = next(r for r in rows if r["store_key"] == "the_body_kyoto")
        assert row_kyoto["grade"] == ""
        assert row_kyoto["date"] == "2026-08-01"

    def test_store_filter_limits_rows(self, _patch_score_snapshots):
        from meo.tools.export import export_score_history
        rows = export_score_history([s for s in _STORES if s["key"] == "the_body_kyoto"])
        assert all(r["store_key"] == "the_body_kyoto" for r in rows)
        assert len(rows) == 2  # one per snapshot date

    def test_empty_snapshots_returns_empty_list(self, monkeypatch):
        from meo.tools.export import export_score_history
        monkeypatch.setattr("meo.tools.export.state.get_score_snapshots", lambda: [])
        rows = export_score_history(_STORES)
        assert rows == []

    def test_stores_in_store_list_order_within_date(self, _patch_score_snapshots):
        from meo.tools.export import export_score_history
        rows = export_score_history(_STORES)
        # Within date 2026-08-04: first row should be _STORES[0]=the_body_kyoto,
        # second should be _STORES[1]=mybear_studio_kyoto
        date_rows = [r for r in rows if r["date"] == "2026-08-04"]
        assert date_rows[0]["store_key"] == "the_body_kyoto"
        assert date_rows[1]["store_key"] == "mybear_studio_kyoto"


# ---------------------------------------------------------------------------
# main() — score-history type
# ---------------------------------------------------------------------------

class TestMainScoreHistory:
    def test_score_history_prints_csv_header(self, capsys, _patch_score_snapshots, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["meo-export", "score-history"])
        from meo.tools.export import main
        main()
        out = capsys.readouterr().out
        assert "date" in out
        assert "grade" in out
        assert "store_key" in out

    def test_score_history_content_in_output(self, capsys, _patch_score_snapshots, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["meo-export", "score-history"])
        from meo.tools.export import main
        main()
        out = capsys.readouterr().out
        assert "2026-08-04" in out
        assert "the_body_kyoto" in out

    def test_score_history_grade_values_in_output(self, capsys, _patch_score_snapshots, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["meo-export", "score-history"])
        from meo.tools.export import main
        main()
        out = capsys.readouterr().out
        assert "A" in out
        assert "D" in out

    def test_score_history_store_filter(self, capsys, _patch_score_snapshots, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["meo-export", "score-history", "--store", "the_body_kyoto"])
        from meo.tools.export import main
        main()
        out = capsys.readouterr().out
        assert "the_body_kyoto" in out
        assert "mybear_studio_kyoto" not in out

    def test_score_history_output_file_created(self, tmp_path, _patch_score_snapshots, monkeypatch):
        out_path = tmp_path / "grades.csv"
        monkeypatch.setattr(sys, "argv", ["meo-export", "score-history", "--output", str(out_path)])
        from meo.tools.export import main
        main()
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8-sig")
        assert "date" in content
        assert "grade" in content

    def test_no_score_history_exits_0_with_helpful_message(self, capsys, _no_history, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["meo-export", "score-history"])
        from meo.tools.export import main
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
        err = capsys.readouterr().err
        assert "meo-score" in err


# ---------------------------------------------------------------------------
# export_answers()
# ---------------------------------------------------------------------------

class TestExportAnswers:
    def test_returns_one_row_per_entry(self, _patch_answer_history):
        from meo.tools.export import export_answers
        rows = export_answers(_STORES)
        assert len(rows) == 2  # 2 entries for kyoto; 0 for mybear

    def test_row_includes_required_fields(self, _patch_answer_history):
        from meo.tools.export import export_answers
        row = export_answers(_STORES)[0]
        assert row["store_key"] == "the_body_kyoto"
        assert row["store_name"] == "THE BODY 京都店"
        assert row["date"] == "2026-01-10"
        assert row["question_id"] == "locations/456/questions/q001"
        assert "駐車場" in row["question"]
        assert "コインパーキング" in row["answer"]

    def test_ordering_matches_history(self, _patch_answer_history):
        from meo.tools.export import export_answers
        rows = export_answers(_STORES)
        assert rows[0]["date"] == "2026-01-10"
        assert rows[1]["date"] == "2026-01-08"

    def test_empty_store_contributes_no_rows(self, _patch_answer_history):
        from meo.tools.export import export_answers
        rows = export_answers([s for s in _STORES if s["key"] == "mybear_studio_kyoto"])
        assert rows == []

    def test_all_stores_combined(self, _patch_answer_history):
        from meo.tools.export import export_answers
        rows = export_answers(_STORES)
        keys = {r["store_key"] for r in rows}
        assert keys == {"the_body_kyoto"}


# ---------------------------------------------------------------------------
# main() — answers type
# ---------------------------------------------------------------------------

class TestMainAnswers:
    def test_answers_prints_csv_header(self, capsys, _patch_answer_history, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["meo-export", "answers"])
        from meo.tools.export import main
        main()
        out = capsys.readouterr().out
        assert "question_id" in out
        assert "question" in out
        assert "answer" in out

    def test_answers_content_in_output(self, capsys, _patch_answer_history, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["meo-export", "answers"])
        from meo.tools.export import main
        main()
        out = capsys.readouterr().out
        assert "the_body_kyoto" in out
        assert "2026-01-10" in out

    def test_answers_store_filter(self, capsys, _patch_answer_history, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["meo-export", "answers", "--store", "the_body_kyoto"])
        from meo.tools.export import main
        main()
        out = capsys.readouterr().out
        assert "the_body_kyoto" in out

    def test_answers_output_file_created(self, tmp_path, _patch_answer_history, monkeypatch):
        out_path = tmp_path / "answers.csv"
        monkeypatch.setattr(sys, "argv", ["meo-export", "answers", "--output", str(out_path)])
        from meo.tools.export import main
        main()
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8-sig")
        assert "question" in content
        assert "answer" in content

    def test_answers_output_file_has_japanese_content(self, tmp_path, _patch_answer_history, monkeypatch):
        out_path = tmp_path / "answers.csv"
        monkeypatch.setattr(sys, "argv", ["meo-export", "answers", "--output", str(out_path)])
        from meo.tools.export import main
        main()
        content = out_path.read_text(encoding="utf-8-sig")
        assert "THE BODY 京都店" in content

    def test_no_answers_exits_0_with_helpful_message(self, capsys, _no_history, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["meo-export", "answers"])
        from meo.tools.export import main
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
        err = capsys.readouterr().err
        assert "Q&A" in err

"""Tests for meo-dismiss — permanently dismiss held reviews."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import meo.state as state_mod
from meo.tools.dismiss import (
    _format_dismiss,
    _format_dismiss_all,
    _format_list,
    _format_undismiss,
    main,
    run_dismiss,
    run_dismiss_all,
    run_list,
    run_undismiss,
)

_STORES = [
    {"key": "store_a", "name": "Store A"},
    {"key": "store_b", "name": "Store B"},
]

_HELD_REVIEWS = [
    {"review_id": "rev001", "reviewer": "Alice", "stars": "ONE", "comment": "悪い"},
    {"review_id": "rev002", "reviewer": "Bob", "stars": "TWO", "comment": "普通"},
]


@pytest.fixture(autouse=True)
def patch_state_file(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(state_mod, "_STATE_FILE", state_file)
    return state_file


@pytest.fixture
def patch_stores(monkeypatch):
    import meo.config as cfg
    monkeypatch.setattr(cfg, "store_list", lambda: _STORES)


# ---------------------------------------------------------------------------
# run_dismiss
# ---------------------------------------------------------------------------

class TestRunDismiss:
    def test_dismiss_adds_review_id(self):
        result = run_dismiss("store_a", "rev001")
        assert result["review_id"] == "rev001"
        assert result["store_key"] == "store_a"
        assert result["already_dismissed"] is False
        assert "rev001" in state_mod.get_dismissed_reviews("store_a")

    def test_dismiss_already_dismissed(self):
        run_dismiss("store_a", "rev001")
        result = run_dismiss("store_a", "rev001")
        assert result["already_dismissed"] is True

    def test_dismiss_removes_from_held_snapshot(self):
        state_mod.record_held_reviews("store_a", _HELD_REVIEWS)
        run_dismiss("store_a", "rev001")
        held = state_mod.get_held_reviews("store_a")
        assert not any(h["review_id"] == "rev001" for h in held)

    def test_dismiss_leaves_other_held_reviews(self):
        state_mod.record_held_reviews("store_a", _HELD_REVIEWS)
        run_dismiss("store_a", "rev001")
        held = state_mod.get_held_reviews("store_a")
        assert any(h["review_id"] == "rev002" for h in held)

    def test_dismiss_does_not_affect_other_stores(self):
        run_dismiss("store_a", "rev001")
        assert "rev001" not in state_mod.get_dismissed_reviews("store_b")


# ---------------------------------------------------------------------------
# run_dismiss_all
# ---------------------------------------------------------------------------

class TestRunDismissAll:
    def test_dismiss_all_held_reviews(self):
        state_mod.record_held_reviews("store_a", _HELD_REVIEWS)
        result = run_dismiss_all("store_a")
        assert result["store_key"] == "store_a"
        assert "rev001" in result["dismissed"]
        assert "rev002" in result["dismissed"]
        assert len(result["dismissed"]) == 2

    def test_dismiss_all_adds_to_dismissed_set(self):
        state_mod.record_held_reviews("store_a", _HELD_REVIEWS)
        run_dismiss_all("store_a")
        dismissed = state_mod.get_dismissed_reviews("store_a")
        assert "rev001" in dismissed
        assert "rev002" in dismissed

    def test_dismiss_all_empty_held_returns_empty_list(self):
        result = run_dismiss_all("store_a")
        assert result["dismissed"] == []

    def test_dismiss_all_skips_held_entries_without_review_id(self):
        held_no_id = [{"reviewer": "Ghost", "stars": "ONE", "comment": "bad"}]
        state_mod.record_held_reviews("store_a", held_no_id)
        result = run_dismiss_all("store_a")
        assert result["dismissed"] == []


# ---------------------------------------------------------------------------
# run_undismiss
# ---------------------------------------------------------------------------

class TestRunUndismiss:
    def test_undismiss_found(self):
        run_dismiss("store_a", "rev001")
        result = run_undismiss("store_a", "rev001")
        assert result["was_dismissed"] is True
        assert "rev001" not in state_mod.get_dismissed_reviews("store_a")

    def test_undismiss_not_found(self):
        result = run_undismiss("store_a", "rev_missing")
        assert result["was_dismissed"] is False

    def test_undismiss_result_includes_review_id_and_store(self):
        run_dismiss("store_b", "rev777")
        result = run_undismiss("store_b", "rev777")
        assert result["review_id"] == "rev777"
        assert result["store_key"] == "store_b"


# ---------------------------------------------------------------------------
# run_list
# ---------------------------------------------------------------------------

class TestRunList:
    def test_list_all_stores(self):
        run_dismiss("store_a", "rev001")
        run_dismiss("store_b", "rev999")
        results = run_list(_STORES)
        assert len(results) == 2
        store_a_result = next(r for r in results if r["store_key"] == "store_a")
        assert "rev001" in store_a_result["dismissed_ids"]

    def test_list_filtered_to_one_store(self):
        run_dismiss("store_a", "rev001")
        run_dismiss("store_b", "rev999")
        results = run_list(_STORES, store_key_filter="store_a")
        assert len(results) == 1
        assert results[0]["store_key"] == "store_a"

    def test_list_empty_when_nothing_dismissed(self):
        results = run_list(_STORES)
        assert all(r["dismissed_ids"] == [] for r in results)

    def test_list_includes_store_name(self):
        results = run_list(_STORES)
        assert results[0]["store_name"] == "Store A"


# ---------------------------------------------------------------------------
# _format_list
# ---------------------------------------------------------------------------

class TestFormatList:
    def test_empty_shows_no_dismissed_message(self):
        results = [{"store_key": "store_a", "store_name": "Store A", "dismissed_ids": []}]
        output = _format_list(results)
        assert "却下済みレビューはありません" in output

    def test_shows_review_ids(self):
        results = [{"store_key": "store_a", "store_name": "Store A", "dismissed_ids": ["rev001", "rev002"]}]
        output = _format_list(results)
        assert "rev001" in output
        assert "rev002" in output

    def test_shows_total_count(self):
        results = [
            {"store_key": "store_a", "store_name": "Store A", "dismissed_ids": ["rev001"]},
            {"store_key": "store_b", "store_name": "Store B", "dismissed_ids": ["rev002", "rev003"]},
        ]
        output = _format_list(results)
        assert "3件" in output

    def test_shows_store_name(self):
        results = [{"store_key": "store_a", "store_name": "Store A", "dismissed_ids": ["rev001"]}]
        output = _format_list(results)
        assert "Store A" in output


# ---------------------------------------------------------------------------
# _format_dismiss / _format_dismiss_all / _format_undismiss
# ---------------------------------------------------------------------------

class TestFormatHelpers:
    def test_format_dismiss_new(self):
        result = {"store_key": "store_a", "review_id": "rev001", "already_dismissed": False}
        assert "rev001" in _format_dismiss(result)
        assert "却下" in _format_dismiss(result)

    def test_format_dismiss_already_dismissed(self):
        result = {"store_key": "store_a", "review_id": "rev001", "already_dismissed": True}
        assert "すでに却下" in _format_dismiss(result)

    def test_format_dismiss_all_success(self):
        result = {"store_key": "store_a", "dismissed": ["rev001", "rev002"]}
        output = _format_dismiss_all(result)
        assert "2件" in output
        assert "rev001" in output

    def test_format_dismiss_all_empty(self):
        result = {"store_key": "store_a", "dismissed": []}
        assert "保留中のレビューはありません" in _format_dismiss_all(result)

    def test_format_undismiss_found(self):
        result = {"store_key": "store_a", "review_id": "rev001", "was_dismissed": True}
        output = _format_undismiss(result)
        assert "rev001" in output
        assert "解除" in output

    def test_format_undismiss_not_found(self):
        result = {"store_key": "store_a", "review_id": "rev_x", "was_dismissed": False}
        assert "見つかりません" in _format_undismiss(result)


# ---------------------------------------------------------------------------
# main() — CLI integration
# ---------------------------------------------------------------------------

class TestMain:
    def _run(self, argv: list[str]) -> tuple[int, str]:
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        code = 0
        with patch("meo.tools.dismiss.cfg.store_list", return_value=_STORES):
            try:
                with redirect_stdout(buf), patch("sys.argv", ["meo-dismiss"] + argv):
                    main()
            except SystemExit as exc:
                code = int(exc.code) if exc.code is not None else 0
        return code, buf.getvalue()

    def test_list_exits_zero(self):
        code, _ = self._run(["--list"])
        assert code == 0

    def test_list_prints_output(self):
        run_dismiss("store_a", "rev001")
        _, out = self._run(["--list"])
        assert "rev001" in out

    def test_dismiss_single_exits_zero(self):
        code, _ = self._run(["--review-id", "rev001", "--store", "store_a"])
        assert code == 0

    def test_dismiss_single_confirms_message(self):
        _, out = self._run(["--review-id", "rev001", "--store", "store_a"])
        assert "rev001" in out

    def test_dismiss_all_exits_zero(self):
        state_mod.record_held_reviews("store_a", _HELD_REVIEWS)
        code, _ = self._run(["--all", "--store", "store_a"])
        assert code == 0

    def test_undismiss_exits_zero(self):
        run_dismiss("store_a", "rev001")
        code, _ = self._run(["--undismiss", "--review-id", "rev001", "--store", "store_a"])
        assert code == 0

    def test_unknown_store_exits_one(self):
        code, _ = self._run(["--review-id", "rev001", "--store", "no_such_store"])
        assert code == 1

    def test_review_id_without_store_exits_one(self):
        code, _ = self._run(["--review-id", "rev001"])
        assert code == 1

    def test_all_without_store_exits_one(self):
        code, _ = self._run(["--all"])
        assert code == 1

    def test_undismiss_without_review_id_exits_one(self):
        code, _ = self._run(["--undismiss", "--store", "store_a"])
        assert code == 1

    def test_undismiss_without_store_exits_one(self):
        code, _ = self._run(["--undismiss", "--review-id", "rev001"])
        assert code == 1

    def test_list_filtered_by_store(self):
        run_dismiss("store_a", "rev001")
        run_dismiss("store_b", "rev999")
        _, out = self._run(["--list", "--store", "store_a"])
        assert "rev001" in out
        assert "rev999" not in out

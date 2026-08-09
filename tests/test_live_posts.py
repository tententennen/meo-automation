"""Tests for meo-live-posts (tools/live_posts.py)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from meo.tools.live_posts import (
    _format_text,
    _parse_create_time,
    _summary_preview,
    check_store_live_posts,
    run_live_posts,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STORE = {
    "key": "the_body_kyoto",
    "name": "THE BODY 京都店",
    "location_id": "accounts/123/locations/456",
    "drive_folder_id": "drive_folder_123",
}

_STORE_NO_LOCATION = {
    "key": "the_body_kyoto",
    "name": "THE BODY 京都店",
    "location_id": "TODO_location_id",
    "drive_folder_id": "drive_folder_123",
}

_LIVE_POST = {
    "name": "accounts/123/locations/456/localPosts/789",
    "summary": "新しいメニューが登場しました！",
    "state": "LIVE",
    "createTime": "2026-01-15T00:00:00Z",
    "updateTime": "2026-01-15T00:00:00Z",
    "topicType": "STANDARD",
}

_PROCESSING_POST = {
    "name": "accounts/123/locations/456/localPosts/790",
    "summary": "お得なキャンペーン中です。",
    "state": "PROCESSING",
    "createTime": "2026-01-16T00:00:00Z",
    "topicType": "STANDARD",
}


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


def test_parse_create_time_utc():
    result = _parse_create_time("2026-01-15T00:00:00Z")
    assert "2026-01-15" in result
    assert "JST" in result


def test_parse_create_time_offset():
    result = _parse_create_time("2026-01-15T09:00:00+09:00")
    assert "2026-01-15" in result


def test_parse_create_time_invalid():
    result = _parse_create_time("not-a-date")
    assert "not-a-date" in result


def test_summary_preview_short():
    text = "短いテキスト"
    assert _summary_preview(text) == "短いテキスト"


def test_summary_preview_long():
    text = "あ" * 100
    result = _summary_preview(text, max_len=10)
    assert result.endswith("…")
    assert len(result) == 11


def test_summary_preview_newlines():
    result = _summary_preview("line1\nline2")
    assert "\n" not in result


# ---------------------------------------------------------------------------
# check_store_live_posts
# ---------------------------------------------------------------------------


def test_check_store_unconfigured_location():
    gbp = MagicMock()
    result = check_store_live_posts(_STORE_NO_LOCATION, gbp)
    assert result["ok"] is False
    assert "TODO" in result["error"] or "location_id" in result["error"]
    gbp.list_local_posts.assert_not_called()


def test_check_store_api_error():
    gbp = MagicMock()
    gbp.list_local_posts.side_effect = RuntimeError("API error")
    result = check_store_live_posts(_STORE, gbp)
    assert result["ok"] is False
    assert "API error" in result["error"]


def test_check_store_no_posts():
    gbp = MagicMock()
    gbp.list_local_posts.return_value = []
    with patch("meo.tools.live_posts.get_post_history", return_value=[]):
        result = check_store_live_posts(_STORE, gbp)
    assert result["ok"] is True
    assert result["live_posts"] == []
    assert result["tracked_count"] == 0
    assert result["untracked_count"] == 0
    assert result["expired_count"] == 0


def test_check_store_live_posts_tracked():
    """A post that is live AND in state.json is counted as tracked."""
    gbp = MagicMock()
    post_name = "accounts/123/locations/456/localPosts/789"
    gbp.list_local_posts.return_value = [{**_LIVE_POST, "name": post_name}]
    archived = [{"date": "2026-01-15", "text": "...", "theme": "", "post_name": post_name}]
    with patch("meo.tools.live_posts.get_post_history", return_value=archived):
        result = check_store_live_posts(_STORE, gbp)
    assert result["ok"] is True
    assert result["tracked_count"] == 1
    assert result["untracked_count"] == 0
    assert result["expired_count"] == 0


def test_check_store_live_posts_untracked():
    """A live post not in state.json is counted as untracked."""
    gbp = MagicMock()
    gbp.list_local_posts.return_value = [_LIVE_POST]
    with patch("meo.tools.live_posts.get_post_history", return_value=[]):
        result = check_store_live_posts(_STORE, gbp)
    assert result["ok"] is True
    assert result["untracked_count"] == 1
    assert result["tracked_count"] == 0


def test_check_store_archived_but_expired():
    """A post in state.json that is not live is counted as expired."""
    gbp = MagicMock()
    gbp.list_local_posts.return_value = []
    archived = [{"date": "2025-06-01", "text": "...", "theme": "", "post_name": "accounts/.../localPosts/old"}]
    with patch("meo.tools.live_posts.get_post_history", return_value=archived):
        result = check_store_live_posts(_STORE, gbp)
    assert result["ok"] is True
    assert result["expired_count"] == 1
    assert result["tracked_count"] == 0


def test_check_store_state_breakdown():
    """State breakdown counts LIVE and PROCESSING separately."""
    gbp = MagicMock()
    gbp.list_local_posts.return_value = [_LIVE_POST, _PROCESSING_POST]
    with patch("meo.tools.live_posts.get_post_history", return_value=[]):
        result = check_store_live_posts(_STORE, gbp)
    assert result["ok"] is True
    assert result["state_breakdown"]["LIVE"] == 1
    assert result["state_breakdown"]["PROCESSING"] == 1


def test_check_store_archived_entry_with_empty_post_name_ignored():
    """Archived entries with empty post_name are ignored in reconciliation."""
    gbp = MagicMock()
    gbp.list_local_posts.return_value = []
    archived = [{"date": "2026-01-15", "text": "...", "theme": "", "post_name": ""}]
    with patch("meo.tools.live_posts.get_post_history", return_value=archived):
        result = check_store_live_posts(_STORE, gbp)
    assert result["expired_count"] == 0


# ---------------------------------------------------------------------------
# run_live_posts
# ---------------------------------------------------------------------------


def test_run_live_posts_auth_error():
    with patch("meo.tools.live_posts.get_credentials", side_effect=EnvironmentError("no creds")):
        results = run_live_posts([_STORE])
    assert len(results) == 1
    assert results[0]["ok"] is False
    assert "no creds" in results[0]["error"]


def test_run_live_posts_success():
    mock_creds = MagicMock()
    mock_gbp = MagicMock()
    mock_gbp.list_local_posts.return_value = [_LIVE_POST]
    with (
        patch("meo.tools.live_posts.get_credentials", return_value=mock_creds),
        patch("meo.tools.live_posts.BusinessProfileClient", return_value=mock_gbp),
        patch("meo.tools.live_posts.get_post_history", return_value=[]),
    ):
        results = run_live_posts([_STORE])
    assert len(results) == 1
    assert results[0]["ok"] is True
    assert len(results[0]["live_posts"]) == 1


def test_run_live_posts_multi_store():
    store_b = {**_STORE, "key": "the_body_osaka_shinsaibashi", "name": "THE BODY 大阪 心斎橋店"}
    mock_creds = MagicMock()
    mock_gbp = MagicMock()
    mock_gbp.list_local_posts.return_value = []
    with (
        patch("meo.tools.live_posts.get_credentials", return_value=mock_creds),
        patch("meo.tools.live_posts.BusinessProfileClient", return_value=mock_gbp),
        patch("meo.tools.live_posts.get_post_history", return_value=[]),
    ):
        results = run_live_posts([_STORE, store_b])
    assert len(results) == 2
    assert all(r["ok"] for r in results)


# ---------------------------------------------------------------------------
# _format_text
# ---------------------------------------------------------------------------


def test_format_text_ok():
    result_ok = {
        "store_key": "the_body_kyoto",
        "store_name": "THE BODY 京都店",
        "ok": True,
        "live_posts": [_LIVE_POST],
        "state_breakdown": {"LIVE": 1},
        "tracked_count": 0,
        "untracked_count": 1,
        "expired_count": 0,
    }
    text = _format_text([result_ok])
    assert "THE BODY 京都店" in text
    assert "公開中" in text
    assert "新しいメニューが登場しました" in text


def test_format_text_error():
    result_err = {
        "store_key": "the_body_kyoto",
        "store_name": "THE BODY 京都店",
        "ok": False,
        "error": "location_id not configured",
    }
    text = _format_text([result_err])
    assert "THE BODY 京都店" in text
    assert "エラー" in text
    assert "location_id" in text


def test_format_text_no_posts():
    result = {
        "store_key": "the_body_kyoto",
        "store_name": "THE BODY 京都店",
        "ok": True,
        "live_posts": [],
        "state_breakdown": {},
        "tracked_count": 0,
        "untracked_count": 0,
        "expired_count": 0,
    }
    text = _format_text([result])
    assert "現在公開中の投稿はありません" in text


def test_format_text_caps_at_10_posts():
    """Only the 10 most recent posts are shown in the text output."""
    posts = [
        {**_LIVE_POST, "name": f"accounts/.../localPosts/{i}", "summary": f"投稿{i}"}
        for i in range(15)
    ]
    result = {
        "store_key": "the_body_kyoto",
        "store_name": "THE BODY 京都店",
        "ok": True,
        "live_posts": posts,
        "state_breakdown": {"LIVE": 15},
        "tracked_count": 0,
        "untracked_count": 15,
        "expired_count": 0,
    }
    text = _format_text([result])
    assert "投稿14" not in text  # post 11-14 should not appear


# ---------------------------------------------------------------------------
# CLI integration (via main())
# ---------------------------------------------------------------------------


def test_main_all_ok(capsys):
    """main() exits 0 when all stores succeed."""
    mock_creds = MagicMock()
    mock_gbp = MagicMock()
    mock_gbp.list_local_posts.return_value = []
    stores = [_STORE]
    with (
        patch("meo.tools.live_posts.cfg.store_list", return_value=stores),
        patch("meo.tools.live_posts.get_credentials", return_value=mock_creds),
        patch("meo.tools.live_posts.BusinessProfileClient", return_value=mock_gbp),
        patch("meo.tools.live_posts.get_post_history", return_value=[]),
        patch("sys.argv", ["meo-live-posts"]),
        pytest.raises(SystemExit) as exc_info,
    ):
        from meo.tools.live_posts import main
        main()
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "THE BODY 京都店" in out


def test_main_error_exit_1(capsys):
    """main() exits 1 when any store fails."""
    stores = [_STORE_NO_LOCATION]
    with (
        patch("meo.tools.live_posts.cfg.store_list", return_value=stores),
        patch("meo.tools.live_posts.get_credentials", return_value=MagicMock()),
        patch("meo.tools.live_posts.BusinessProfileClient", return_value=MagicMock()),
        patch("sys.argv", ["meo-live-posts"]),
        pytest.raises(SystemExit) as exc_info,
    ):
        from meo.tools.live_posts import main
        main()
    assert exc_info.value.code == 1


def test_main_json_output(capsys):
    """--json flag produces valid JSON output without live_posts detail."""
    mock_creds = MagicMock()
    mock_gbp = MagicMock()
    mock_gbp.list_local_posts.return_value = [_LIVE_POST]
    stores = [_STORE]
    with (
        patch("meo.tools.live_posts.cfg.store_list", return_value=stores),
        patch("meo.tools.live_posts.get_credentials", return_value=mock_creds),
        patch("meo.tools.live_posts.BusinessProfileClient", return_value=mock_gbp),
        patch("meo.tools.live_posts.get_post_history", return_value=[]),
        patch("sys.argv", ["meo-live-posts", "--json"]),
        pytest.raises(SystemExit),
    ):
        from meo.tools.live_posts import main
        main()
    out = capsys.readouterr().out
    data = json.loads(out)
    assert isinstance(data, list)
    assert data[0]["store_key"] == "the_body_kyoto"
    assert "live_posts" not in data[0]


def test_main_unknown_store(capsys):
    """Unknown --store key exits 1 with error message."""
    stores = [_STORE]
    with (
        patch("meo.tools.live_posts.cfg.store_list", return_value=stores),
        patch("sys.argv", ["meo-live-posts", "--store", "nonexistent_store"]),
        pytest.raises(SystemExit) as exc_info,
    ):
        from meo.tools.live_posts import main
        main()
    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "nonexistent_store" in err


def test_main_filtered_store(capsys):
    """--store filters to only the specified store."""
    store_b = {**_STORE, "key": "the_body_osaka_shinsaibashi", "name": "THE BODY 大阪 心斎橋店"}
    mock_creds = MagicMock()
    mock_gbp = MagicMock()
    mock_gbp.list_local_posts.return_value = []
    stores = [_STORE, store_b]
    with (
        patch("meo.tools.live_posts.cfg.store_list", return_value=stores),
        patch("meo.tools.live_posts.get_credentials", return_value=mock_creds),
        patch("meo.tools.live_posts.BusinessProfileClient", return_value=mock_gbp),
        patch("meo.tools.live_posts.get_post_history", return_value=[]),
        patch("sys.argv", ["meo-live-posts", "--store", "the_body_kyoto"]),
        pytest.raises(SystemExit) as exc_info,
    ):
        from meo.tools.live_posts import main
        main()
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "THE BODY 京都店" in out
    assert "THE BODY 大阪 心斎橋店" not in out

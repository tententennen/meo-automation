"""Tests for meo-reply-manual — fully mocked, no Google credentials needed."""

from unittest.mock import MagicMock, patch
import pytest

from meo.tools.reply_manual import (
    _find_held_review,
    _held_to_gbp_review,
    _remove_from_held,
    run_reply_manual,
    _GBP_REPLY_TEXT_LIMIT,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_STORE = {
    "key": "the_body_kyoto",
    "name": "THE BODY 京都店",
    "industry": "beauty_salon",
    "location_id": "accounts/1/locations/2",
}

_STORE_UNCONFIGURED = {
    "key": "the_body_kyoto",
    "name": "THE BODY 京都店",
    "industry": "beauty_salon",
    "location_id": "TODO_location_id",
}

_STORE_MISSING_LOCATION = {
    "key": "the_body_kyoto",
    "name": "THE BODY 京都店",
    "industry": "beauty_salon",
    "location_id": "",
}

_HELD_REVIEW = {
    "review_id": "rev_abc123",
    "reviewer": "田中太郎",
    "stars": "TWO",
    "comment": "店員の対応がよくなかったです。",
    "date": "2026-08-10",
}

_REPLY_TEXT = "この度はご不便をおかけしてしまい、誠に申し訳ございません。"
_REVIEW_ID = "rev_abc123"


def _make_gbp() -> MagicMock:
    gbp = MagicMock()
    gbp.reply_to_review.return_value = {"comment": _REPLY_TEXT}
    return gbp


# ---------------------------------------------------------------------------
# _find_held_review
# ---------------------------------------------------------------------------

def test_find_held_review_returns_match():
    held = [_HELD_REVIEW, {"review_id": "other_id", "reviewer": "X", "stars": "FIVE", "comment": ""}]
    with patch("meo.tools.reply_manual.get_held_reviews", return_value=held):
        result = _find_held_review("the_body_kyoto", "rev_abc123")
    assert result == _HELD_REVIEW


def test_find_held_review_returns_none_when_not_found():
    with patch("meo.tools.reply_manual.get_held_reviews", return_value=[]):
        result = _find_held_review("the_body_kyoto", "nonexistent_id")
    assert result is None


def test_find_held_review_returns_none_for_different_store():
    held = [_HELD_REVIEW]
    with patch("meo.tools.reply_manual.get_held_reviews", return_value=[]):
        result = _find_held_review("the_body_osaka_shinsaibashi", "rev_abc123")
    assert result is None


# ---------------------------------------------------------------------------
# _held_to_gbp_review
# ---------------------------------------------------------------------------

def test_held_to_gbp_review_maps_fields():
    result = _held_to_gbp_review(_HELD_REVIEW)
    assert result["reviewer"]["displayName"] == "田中太郎"
    assert result["starRating"] == "TWO"
    assert result["comment"] == "店員の対応がよくなかったです。"


def test_held_to_gbp_review_handles_missing_fields():
    result = _held_to_gbp_review({})
    assert result["reviewer"]["displayName"] == ""
    assert result["starRating"] == "FIVE"
    assert result["comment"] == ""


def test_held_to_gbp_review_preserves_all_star_ratings():
    for star in ("ONE", "TWO", "THREE", "FOUR", "FIVE"):
        result = _held_to_gbp_review({"stars": star})
        assert result["starRating"] == star


# ---------------------------------------------------------------------------
# _remove_from_held
# ---------------------------------------------------------------------------

def test_remove_from_held_removes_correct_entry():
    other = {"review_id": "other_id", "reviewer": "X", "stars": "FIVE", "comment": ""}
    held = [_HELD_REVIEW, other]
    with patch("meo.tools.reply_manual.get_held_reviews", return_value=held) as _mock_get, \
         patch("meo.tools.reply_manual.record_held_reviews") as mock_rec:
        _remove_from_held("the_body_kyoto", "rev_abc123")
    saved = mock_rec.call_args[0][1]
    assert len(saved) == 1
    assert saved[0]["review_id"] == "other_id"


def test_remove_from_held_keeps_all_when_id_not_found():
    with patch("meo.tools.reply_manual.get_held_reviews", return_value=[_HELD_REVIEW]) as _mock_get, \
         patch("meo.tools.reply_manual.record_held_reviews") as mock_rec:
        _remove_from_held("the_body_kyoto", "nonexistent_id")
    saved = mock_rec.call_args[0][1]
    assert len(saved) == 1


def test_remove_from_held_with_empty_snapshot():
    with patch("meo.tools.reply_manual.get_held_reviews", return_value=[]) as _mock_get, \
         patch("meo.tools.reply_manual.record_held_reviews") as mock_rec:
        _remove_from_held("the_body_kyoto", "rev_abc123")
    mock_rec.assert_called_once_with("the_body_kyoto", [])


# ---------------------------------------------------------------------------
# run_reply_manual — validation
# ---------------------------------------------------------------------------

def test_raises_on_todo_location_id():
    with pytest.raises(ValueError, match="location_id is not configured"):
        run_reply_manual(_STORE_UNCONFIGURED, _REVIEW_ID, _REPLY_TEXT, _make_gbp())


def test_raises_on_empty_location_id():
    with pytest.raises(ValueError, match="location_id is not configured"):
        run_reply_manual(_STORE_MISSING_LOCATION, _REVIEW_ID, _REPLY_TEXT, _make_gbp())


# ---------------------------------------------------------------------------
# run_reply_manual — dry run
# ---------------------------------------------------------------------------

def test_dry_run_returns_dry_run_status():
    with patch("meo.tools.reply_manual._remove_from_held"):
        result = run_reply_manual(_STORE, _REVIEW_ID, _REPLY_TEXT, _make_gbp(), dry_run=True)
    assert result["status"] == "dry_run"
    assert result["review_id"] == _REVIEW_ID
    assert result["reply_text"] == _REPLY_TEXT
    assert result["store_key"] == "the_body_kyoto"


def test_dry_run_does_not_call_gbp_api():
    gbp = _make_gbp()
    with patch("meo.tools.reply_manual._remove_from_held"):
        run_reply_manual(_STORE, _REVIEW_ID, _REPLY_TEXT, gbp, dry_run=True)
    gbp.reply_to_review.assert_not_called()


def test_dry_run_does_not_write_state():
    with patch("meo.tools.reply_manual.record_replied_review") as mock_rr, \
         patch("meo.tools.reply_manual.record_reply_content") as mock_rc, \
         patch("meo.tools.reply_manual._remove_from_held") as mock_remove:
        run_reply_manual(_STORE, _REVIEW_ID, _REPLY_TEXT, _make_gbp(), dry_run=True)
    mock_rr.assert_not_called()
    mock_rc.assert_not_called()
    mock_remove.assert_not_called()


# ---------------------------------------------------------------------------
# run_reply_manual — live run
# ---------------------------------------------------------------------------

def test_live_calls_reply_to_review():
    gbp = _make_gbp()
    with patch("meo.tools.reply_manual.record_replied_review"), \
         patch("meo.tools.reply_manual.record_reply_content"), \
         patch("meo.tools.reply_manual._remove_from_held"):
        run_reply_manual(_STORE, _REVIEW_ID, _REPLY_TEXT, gbp, dry_run=False)
    gbp.reply_to_review.assert_called_once_with(
        _STORE["location_id"], _REVIEW_ID, _REPLY_TEXT
    )


def test_live_records_replied_review():
    with patch("meo.tools.reply_manual.record_replied_review") as mock_rr, \
         patch("meo.tools.reply_manual.record_reply_content"), \
         patch("meo.tools.reply_manual._remove_from_held"):
        run_reply_manual(_STORE, _REVIEW_ID, _REPLY_TEXT, _make_gbp())
    mock_rr.assert_called_once_with("the_body_kyoto", _REVIEW_ID)


def test_live_records_reply_content_with_reviewer_and_stars():
    with patch("meo.tools.reply_manual.record_replied_review"), \
         patch("meo.tools.reply_manual.record_reply_content") as mock_rc, \
         patch("meo.tools.reply_manual._remove_from_held"):
        run_reply_manual(
            _STORE, _REVIEW_ID, _REPLY_TEXT, _make_gbp(),
            reviewer="田中太郎", stars="TWO",
        )
    mock_rc.assert_called_once_with(
        "the_body_kyoto", _REVIEW_ID, "田中太郎", "TWO", _REPLY_TEXT
    )


def test_live_records_reply_content_with_empty_defaults():
    with patch("meo.tools.reply_manual.record_replied_review"), \
         patch("meo.tools.reply_manual.record_reply_content") as mock_rc, \
         patch("meo.tools.reply_manual._remove_from_held"):
        run_reply_manual(_STORE, _REVIEW_ID, _REPLY_TEXT, _make_gbp())
    mock_rc.assert_called_once_with("the_body_kyoto", _REVIEW_ID, "", "", _REPLY_TEXT)


def test_live_removes_from_held():
    with patch("meo.tools.reply_manual.record_replied_review"), \
         patch("meo.tools.reply_manual.record_reply_content"), \
         patch("meo.tools.reply_manual._remove_from_held") as mock_remove:
        run_reply_manual(_STORE, _REVIEW_ID, _REPLY_TEXT, _make_gbp())
    mock_remove.assert_called_once_with("the_body_kyoto", _REVIEW_ID)


def test_live_returns_replied_status():
    with patch("meo.tools.reply_manual.record_replied_review"), \
         patch("meo.tools.reply_manual.record_reply_content"), \
         patch("meo.tools.reply_manual._remove_from_held"):
        result = run_reply_manual(_STORE, _REVIEW_ID, _REPLY_TEXT, _make_gbp())
    assert result["status"] == "replied"
    assert result["review_id"] == _REVIEW_ID
    assert result["store_key"] == "the_body_kyoto"


# ---------------------------------------------------------------------------
# run_reply_manual — text length warning
# ---------------------------------------------------------------------------

def test_long_reply_logs_warning(caplog):
    gbp = _make_gbp()
    long_text = "あ" * (_GBP_REPLY_TEXT_LIMIT + 1)
    with patch("meo.tools.reply_manual.record_replied_review"), \
         patch("meo.tools.reply_manual.record_reply_content"), \
         patch("meo.tools.reply_manual._remove_from_held"), \
         caplog.at_level("WARNING"):
        run_reply_manual(_STORE, _REVIEW_ID, long_text, gbp)
    assert any("chars" in r.message.lower() or "limit" in r.message.lower() for r in caplog.records)


def test_reply_at_limit_does_not_warn(caplog):
    gbp = _make_gbp()
    ok_text = "あ" * _GBP_REPLY_TEXT_LIMIT
    with patch("meo.tools.reply_manual.record_replied_review"), \
         patch("meo.tools.reply_manual.record_reply_content"), \
         patch("meo.tools.reply_manual._remove_from_held"), \
         caplog.at_level("WARNING"):
        run_reply_manual(_STORE, _REVIEW_ID, ok_text, gbp)
    length_warnings = [
        r for r in caplog.records
        if "chars" in r.message.lower() or "limit" in r.message.lower()
    ]
    assert not length_warnings


# ---------------------------------------------------------------------------
# main() — shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_store_list():
    return [
        {
            "key": "the_body_kyoto",
            "name": "THE BODY 京都店",
            "industry": "beauty_salon",
            "location_id": "accounts/1/locations/2",
        }
    ]


@pytest.fixture
def mock_held_reviews():
    return [_HELD_REVIEW]


# ---------------------------------------------------------------------------
# main() — unknown store
# ---------------------------------------------------------------------------

def test_main_unknown_store_exits_1(mock_store_list, capsys):
    with patch("meo.tools.reply_manual.cfg.store_list", return_value=mock_store_list):
        with pytest.raises(SystemExit) as exc_info:
            import sys
            sys.argv = [
                "meo-reply-manual", "--store", "nonexistent_store",
                "--review", _REVIEW_ID, "--text", _REPLY_TEXT,
            ]
            from meo.tools.reply_manual import main
            main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Unknown store key" in captured.err


# ---------------------------------------------------------------------------
# main() — --auto, review not in held snapshot
# ---------------------------------------------------------------------------

def test_main_auto_review_not_in_held_exits_1(mock_store_list, capsys):
    with patch("meo.tools.reply_manual.cfg.store_list", return_value=mock_store_list), \
         patch("meo.tools.reply_manual._find_held_review", return_value=None):
        with pytest.raises(SystemExit) as exc_info:
            import sys
            sys.argv = [
                "meo-reply-manual", "--store", "the_body_kyoto",
                "--review", _REVIEW_ID, "--auto",
            ]
            from meo.tools.reply_manual import main
            main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "not found" in captured.err


# ---------------------------------------------------------------------------
# main() — --auto, AI generation fails
# ---------------------------------------------------------------------------

def test_main_auto_generate_reply_failure_exits_1(mock_store_list, capsys):
    with patch("meo.tools.reply_manual.cfg.store_list", return_value=mock_store_list), \
         patch("meo.tools.reply_manual._find_held_review", return_value=_HELD_REVIEW), \
         patch("meo.tools.reply_manual.generate_reply", side_effect=RuntimeError("API error")):
        with pytest.raises(SystemExit) as exc_info:
            import sys
            sys.argv = [
                "meo-reply-manual", "--store", "the_body_kyoto",
                "--review", _REVIEW_ID, "--auto",
            ]
            from meo.tools.reply_manual import main
            main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "generation failed" in captured.err.lower()


# ---------------------------------------------------------------------------
# main() — --auto, successful live run
# ---------------------------------------------------------------------------

def test_main_auto_live_posts_generated_reply(mock_store_list, capsys):
    with patch("meo.tools.reply_manual.cfg.store_list", return_value=mock_store_list), \
         patch("meo.tools.reply_manual._find_held_review", return_value=_HELD_REVIEW), \
         patch("meo.tools.reply_manual.generate_reply", return_value=_REPLY_TEXT), \
         patch("meo.tools.reply_manual.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.reply_manual.BusinessProfileClient") as MockGBP, \
         patch("meo.tools.reply_manual.record_replied_review"), \
         patch("meo.tools.reply_manual.record_reply_content"), \
         patch("meo.tools.reply_manual._remove_from_held"):
        MockGBP.return_value.reply_to_review.return_value = {}
        import sys
        sys.argv = [
            "meo-reply-manual", "--store", "the_body_kyoto",
            "--review", _REVIEW_ID, "--auto",
        ]
        from meo.tools.reply_manual import main
        main()
    MockGBP.return_value.reply_to_review.assert_called_once_with(
        "accounts/1/locations/2", _REVIEW_ID, _REPLY_TEXT
    )
    captured = capsys.readouterr()
    assert "[DRY RUN]" not in captured.out
    assert _REVIEW_ID in captured.out


# ---------------------------------------------------------------------------
# main() — --auto, dry run
# ---------------------------------------------------------------------------

def test_main_auto_dry_run_does_not_call_api(mock_store_list, capsys):
    with patch("meo.tools.reply_manual.cfg.store_list", return_value=mock_store_list), \
         patch("meo.tools.reply_manual._find_held_review", return_value=_HELD_REVIEW), \
         patch("meo.tools.reply_manual.generate_reply", return_value=_REPLY_TEXT), \
         patch("meo.tools.reply_manual.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.reply_manual.BusinessProfileClient") as MockGBP:
        import sys
        sys.argv = [
            "meo-reply-manual", "--store", "the_body_kyoto",
            "--review", _REVIEW_ID, "--auto", "--dry-run",
        ]
        from meo.tools.reply_manual import main
        main()
    MockGBP.return_value.reply_to_review.assert_not_called()
    captured = capsys.readouterr()
    assert "[DRY RUN]" in captured.out


# ---------------------------------------------------------------------------
# main() — --text, successful live run
# ---------------------------------------------------------------------------

def test_main_text_live_posts_supplied_reply(mock_store_list, capsys):
    with patch("meo.tools.reply_manual.cfg.store_list", return_value=mock_store_list), \
         patch("meo.tools.reply_manual._find_held_review", return_value=_HELD_REVIEW), \
         patch("meo.tools.reply_manual.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.reply_manual.BusinessProfileClient") as MockGBP, \
         patch("meo.tools.reply_manual.record_replied_review"), \
         patch("meo.tools.reply_manual.record_reply_content"), \
         patch("meo.tools.reply_manual._remove_from_held"):
        MockGBP.return_value.reply_to_review.return_value = {}
        import sys
        sys.argv = [
            "meo-reply-manual", "--store", "the_body_kyoto",
            "--review", _REVIEW_ID, "--text", _REPLY_TEXT,
        ]
        from meo.tools.reply_manual import main
        main()
    MockGBP.return_value.reply_to_review.assert_called_once_with(
        "accounts/1/locations/2", _REVIEW_ID, _REPLY_TEXT
    )
    captured = capsys.readouterr()
    assert "[DRY RUN]" not in captured.out
    assert _REVIEW_ID in captured.out


# ---------------------------------------------------------------------------
# main() — --text, review not in held snapshot (warn but proceed)
# ---------------------------------------------------------------------------

def test_main_text_review_not_in_held_warns_but_proceeds(mock_store_list, capsys, caplog):
    with patch("meo.tools.reply_manual.cfg.store_list", return_value=mock_store_list), \
         patch("meo.tools.reply_manual._find_held_review", return_value=None), \
         patch("meo.tools.reply_manual.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.reply_manual.BusinessProfileClient") as MockGBP, \
         patch("meo.tools.reply_manual.record_replied_review"), \
         patch("meo.tools.reply_manual.record_reply_content"), \
         patch("meo.tools.reply_manual._remove_from_held"), \
         caplog.at_level("WARNING"):
        MockGBP.return_value.reply_to_review.return_value = {}
        import sys
        sys.argv = [
            "meo-reply-manual", "--store", "the_body_kyoto",
            "--review", "unknown_rev", "--text", _REPLY_TEXT,
        ]
        from meo.tools.reply_manual import main
        main()
    MockGBP.return_value.reply_to_review.assert_called_once()
    assert any("not found" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# main() — --text, dry run
# ---------------------------------------------------------------------------

def test_main_text_dry_run(mock_store_list, capsys):
    with patch("meo.tools.reply_manual.cfg.store_list", return_value=mock_store_list), \
         patch("meo.tools.reply_manual._find_held_review", return_value=_HELD_REVIEW), \
         patch("meo.tools.reply_manual.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.reply_manual.BusinessProfileClient") as MockGBP:
        import sys
        sys.argv = [
            "meo-reply-manual", "--store", "the_body_kyoto",
            "--review", _REVIEW_ID, "--text", _REPLY_TEXT, "--dry-run",
        ]
        from meo.tools.reply_manual import main
        main()
    MockGBP.return_value.reply_to_review.assert_not_called()
    captured = capsys.readouterr()
    assert "[DRY RUN]" in captured.out


# ---------------------------------------------------------------------------
# main() — auth failure
# ---------------------------------------------------------------------------

def test_main_auth_failure_exits_1(mock_store_list, capsys):
    with patch("meo.tools.reply_manual.cfg.store_list", return_value=mock_store_list), \
         patch("meo.tools.reply_manual._find_held_review", return_value=_HELD_REVIEW), \
         patch("meo.tools.reply_manual.get_credentials", side_effect=RuntimeError("no creds")):
        with pytest.raises(SystemExit) as exc_info:
            import sys
            sys.argv = [
                "meo-reply-manual", "--store", "the_body_kyoto",
                "--review", _REVIEW_ID, "--text", _REPLY_TEXT,
            ]
            from meo.tools.reply_manual import main
            main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Authentication failed" in captured.err


# ---------------------------------------------------------------------------
# main() — ValueError from run_reply_manual (unconfigured location_id)
# ---------------------------------------------------------------------------

def test_main_value_error_exits_1(mock_store_list, capsys):
    unconfigured = [{**mock_store_list[0], "location_id": "TODO_location_id"}]
    with patch("meo.tools.reply_manual.cfg.store_list", return_value=unconfigured), \
         patch("meo.tools.reply_manual._find_held_review", return_value=_HELD_REVIEW), \
         patch("meo.tools.reply_manual.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.reply_manual.BusinessProfileClient"):
        with pytest.raises(SystemExit) as exc_info:
            import sys
            sys.argv = [
                "meo-reply-manual", "--store", "the_body_kyoto",
                "--review", _REVIEW_ID, "--text", _REPLY_TEXT,
            ]
            from meo.tools.reply_manual import main
            main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err


# ---------------------------------------------------------------------------
# main() — unexpected API error
# ---------------------------------------------------------------------------

def test_main_unexpected_api_error_exits_1(mock_store_list, capsys):
    with patch("meo.tools.reply_manual.cfg.store_list", return_value=mock_store_list), \
         patch("meo.tools.reply_manual._find_held_review", return_value=_HELD_REVIEW), \
         patch("meo.tools.reply_manual.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.reply_manual.BusinessProfileClient") as MockGBP:
        MockGBP.return_value.reply_to_review.side_effect = RuntimeError("network timeout")
        with pytest.raises(SystemExit) as exc_info:
            import sys
            sys.argv = [
                "meo-reply-manual", "--store", "the_body_kyoto",
                "--review", _REVIEW_ID, "--text", _REPLY_TEXT,
            ]
            from meo.tools.reply_manual import main
            main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Unexpected error" in captured.err

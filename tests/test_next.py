"""Tests for meo-next — next scheduled run preview."""

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

import meo.state as state_mod
from meo.tools.next import (
    _check_time_window,
    _format_output,
    _next_run_date,
    run_next,
)

_JST = ZoneInfo("Asia/Tokyo")

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_STORE_OSAKA = {
    "key": "the_body_osaka_shinsaibashi",
    "name": "THE BODY 大阪 心斎橋店",
    "location_id": "accounts/1/locations/1",
    "drive_folder_id": "drive_osaka_abc",
    "industry": "beauty_salon",
}

_STORE_KYOTO = {
    "key": "the_body_kyoto",
    "name": "THE BODY 京都店",
    "location_id": "accounts/1/locations/2",
    "drive_folder_id": "TODO: Google Drive folder ID",
    "industry": "beauty_salon",
}

_STORE_MYBEAR = {
    "key": "mybear_studio_kyoto",
    "name": "MYBEAR STUDIO 京都店",
    "location_id": "accounts/1/locations/3",
    "drive_folder_id": "",
    "industry": "fitness_studio",
}

_ALL_STORES = [_STORE_OSAKA, _STORE_KYOTO, _STORE_MYBEAR]

_NEXT_DATE = date(2026, 8, 7)  # arbitrary fixed "next run" date for testing


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """Redirect state.json to a clean temp directory for every test."""
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(state_mod, "_STATE_FILE", state_file)


@pytest.fixture
def _patch_store_list(monkeypatch):
    """Patch config.store_list() to return our test stores."""
    import meo.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "store_list", lambda: list(_ALL_STORES))


@pytest.fixture
def _patch_effective_defaults(monkeypatch):
    """Patch effective_defaults to return a minimal defaults dict."""
    import meo.config as cfg_mod
    monkeypatch.setattr(
        cfg_mod,
        "effective_defaults",
        lambda store: {"post_cadence_days": 1, "post_time_window_jst": "06:00-23:00"},
    )


# ---------------------------------------------------------------------------
# _check_time_window
# ---------------------------------------------------------------------------

class TestCheckTimeWindow:
    def test_none_window_returns_true(self):
        assert _check_time_window(None, time(12, 0)) is True

    def test_empty_string_window_returns_true(self):
        assert _check_time_window("", time(12, 0)) is True

    def test_inside_normal_window(self):
        assert _check_time_window("06:00-23:00", time(10, 0)) is True

    def test_outside_normal_window(self):
        assert _check_time_window("06:00-23:00", time(2, 0)) is False

    def test_at_window_start_inclusive(self):
        assert _check_time_window("06:00-23:00", time(6, 0)) is True

    def test_at_window_end_inclusive(self):
        assert _check_time_window("06:00-23:00", time(23, 0)) is True

    def test_midnight_crossing_inside_late(self):
        assert _check_time_window("22:00-06:00", time(23, 30)) is True

    def test_midnight_crossing_inside_early(self):
        assert _check_time_window("22:00-06:00", time(3, 0)) is True

    def test_midnight_crossing_outside(self):
        assert _check_time_window("22:00-06:00", time(12, 0)) is False

    def test_invalid_format_returns_true(self):
        assert _check_time_window("bad-format", time(9, 0)) is True

    def test_invalid_hour_value_returns_true(self):
        # Pattern won't match if hours aren't two digits, but test parse fallback
        assert _check_time_window("6:00-23:00", time(9, 0)) is True

    def test_out_of_range_hour_passes_regex_but_raises_value_error_returns_true(self):
        # "25:00-23:00" matches the \d{2}:\d{2}-\d{2}:\d{2} regex but time(25,0) raises ValueError
        assert _check_time_window("25:00-23:00", time(9, 0)) is True


# ---------------------------------------------------------------------------
# _next_run_date
# ---------------------------------------------------------------------------

class TestNextRunDate:
    def test_before_nine_returns_today(self):
        now = datetime(2026, 8, 6, 8, 30, tzinfo=_JST)  # 08:30 JST
        assert _next_run_date(now) == date(2026, 8, 6)

    def test_after_nine_returns_tomorrow(self):
        now = datetime(2026, 8, 6, 10, 0, tzinfo=_JST)  # 10:00 JST
        assert _next_run_date(now) == date(2026, 8, 7)

    def test_exactly_nine_returns_tomorrow(self):
        now = datetime(2026, 8, 6, 9, 0, tzinfo=_JST)  # 09:00 JST
        assert _next_run_date(now) == date(2026, 8, 7)

    def test_no_arg_returns_a_date(self):
        result = _next_run_date()
        assert isinstance(result, date)


class TestRunNextDefaultDate:
    def test_run_next_without_next_date_uses_next_run_date(self, monkeypatch):
        """run_next(next_date=None) falls through to _next_run_date()."""
        import meo.config as cfg_mod
        import meo.state as state_mod_inner

        monkeypatch.setattr(cfg_mod, "store_list", lambda: [_STORE_OSAKA])
        monkeypatch.setattr(
            cfg_mod, "effective_defaults",
            lambda s: {"post_cadence_days": 1, "post_time_window_jst": None},
        )
        # Patch _next_run_date to return a known date so the result is deterministic.
        fixed = date(2026, 8, 10)
        from meo.tools import next as next_mod
        monkeypatch.setattr(next_mod, "_next_run_date", lambda: fixed)
        result = run_next([_STORE_OSAKA])  # no next_date arg
        assert result["next_run_date"] == fixed.isoformat()


# ---------------------------------------------------------------------------
# run_next — return structure
# ---------------------------------------------------------------------------

class TestRunNextStructure:
    def test_returns_required_top_level_keys(self, _patch_effective_defaults):
        result = run_next([_STORE_OSAKA], next_date=_NEXT_DATE)
        assert "next_run_date" in result
        assert "next_run_time_jst" in result
        assert "stores" in result

    def test_next_run_date_matches_arg(self, _patch_effective_defaults):
        result = run_next([_STORE_OSAKA], next_date=_NEXT_DATE)
        assert result["next_run_date"] == _NEXT_DATE.isoformat()

    def test_next_run_time_default_is_nine(self, _patch_effective_defaults):
        result = run_next([_STORE_OSAKA], next_date=_NEXT_DATE)
        assert result["next_run_time_jst"] == "09:00"

    def test_custom_scheduled_time_reflected(self, _patch_effective_defaults):
        result = run_next([_STORE_OSAKA], next_date=_NEXT_DATE, scheduled_time=time(14, 0))
        assert result["next_run_time_jst"] == "14:00"

    def test_one_result_per_store(self, _patch_effective_defaults):
        result = run_next(_ALL_STORES, next_date=_NEXT_DATE)
        assert len(result["stores"]) == 3

    def test_store_result_has_required_keys(self, _patch_effective_defaults):
        sr = run_next([_STORE_OSAKA], next_date=_NEXT_DATE)["stores"][0]
        for key in (
            "store_key", "name", "post_action", "last_post", "cadence_days",
            "next_post_due", "days_until_due", "time_window", "time_window_ok",
            "drive_configured", "held_review_count",
        ):
            assert key in sr, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# run_next — post_action logic
# ---------------------------------------------------------------------------

class TestRunNextPostAction:
    def test_no_last_post_action_is_post(self, _patch_effective_defaults):
        sr = run_next([_STORE_OSAKA], next_date=_NEXT_DATE)["stores"][0]
        assert sr["post_action"] == "post"
        assert sr["last_post"] is None

    def test_last_post_yesterday_cadence_1_action_is_post(self, _patch_effective_defaults):
        yesterday = (_NEXT_DATE - timedelta(days=1)).isoformat()
        state_mod._STATE_FILE.write_text(
            json.dumps({"last_post": {"the_body_osaka_shinsaibashi": yesterday}})
        )
        sr = run_next([_STORE_OSAKA], next_date=_NEXT_DATE)["stores"][0]
        assert sr["post_action"] == "post"

    def test_last_post_on_next_date_cadence_1_action_is_skip(self, _patch_effective_defaults):
        # last_post=2026-08-07, cadence=1 → due_date=2026-08-08 > next_date → skip
        state_mod._STATE_FILE.write_text(
            json.dumps({"last_post": {"the_body_osaka_shinsaibashi": _NEXT_DATE.isoformat()}})
        )
        sr = run_next([_STORE_OSAKA], next_date=_NEXT_DATE)["stores"][0]
        assert sr["post_action"] == "skip"

    def test_last_post_today_cadence_2_action_is_skip(self, _patch_effective_defaults):
        import meo.config as cfg_mod
        # Override cadence to 2 days
        from meo.tools.next import _check_time_window as ctw
        with patch.object(cfg_mod, "effective_defaults",
                          return_value={"post_cadence_days": 2,
                                        "post_time_window_jst": "06:00-23:00"}):
            # last post on next_date → due on next_date+2 → skip next_date
            state_mod._STATE_FILE.write_text(
                json.dumps({"last_post": {"the_body_osaka_shinsaibashi": _NEXT_DATE.isoformat()}})
            )
            sr = run_next([_STORE_OSAKA], next_date=_NEXT_DATE)["stores"][0]
            assert sr["post_action"] == "skip"

    def test_skip_populates_next_post_due(self, monkeypatch):
        import meo.config as cfg_mod
        monkeypatch.setattr(
            cfg_mod, "effective_defaults",
            lambda store: {"post_cadence_days": 3, "post_time_window_jst": None},
        )
        # last post on 2026-08-05: due on 2026-08-08, but next_date=2026-08-07 → skip
        state_mod._STATE_FILE.write_text(
            json.dumps({"last_post": {"the_body_osaka_shinsaibashi": "2026-08-05"}})
        )
        sr = run_next([_STORE_OSAKA], next_date=date(2026, 8, 7))["stores"][0]
        assert sr["post_action"] == "skip"
        assert sr["next_post_due"] == "2026-08-08"
        assert sr["days_until_due"] == 1

    def test_skip_window_when_post_due_but_outside_window(self, monkeypatch):
        import meo.config as cfg_mod
        # Window 22:00-06:00 — 09:00 falls outside
        monkeypatch.setattr(
            cfg_mod, "effective_defaults",
            lambda store: {"post_cadence_days": 1, "post_time_window_jst": "22:00-06:00"},
        )
        sr = run_next([_STORE_OSAKA], next_date=_NEXT_DATE, scheduled_time=time(9, 0))["stores"][0]
        assert sr["post_action"] == "skip_window"
        assert sr["time_window_ok"] is False

    def test_post_due_and_inside_window_action_is_post(self, monkeypatch):
        import meo.config as cfg_mod
        monkeypatch.setattr(
            cfg_mod, "effective_defaults",
            lambda store: {"post_cadence_days": 1, "post_time_window_jst": "06:00-23:00"},
        )
        sr = run_next([_STORE_OSAKA], next_date=_NEXT_DATE, scheduled_time=time(9, 0))["stores"][0]
        assert sr["post_action"] == "post"
        assert sr["time_window_ok"] is True

    def test_invalid_last_post_date_treated_as_never_posted(self, _patch_effective_defaults):
        state_mod._STATE_FILE.write_text(
            json.dumps({"last_post": {"the_body_osaka_shinsaibashi": "not-a-date"}})
        )
        sr = run_next([_STORE_OSAKA], next_date=_NEXT_DATE)["stores"][0]
        assert sr["post_action"] == "post"
        assert sr["last_post"] is None


# ---------------------------------------------------------------------------
# run_next — drive_configured and held_review_count
# ---------------------------------------------------------------------------

class TestRunNextMeta:
    def test_drive_configured_true_for_real_folder_id(self, _patch_effective_defaults):
        sr = run_next([_STORE_OSAKA], next_date=_NEXT_DATE)["stores"][0]
        assert sr["drive_configured"] is True

    def test_drive_configured_false_for_todo_placeholder(self, _patch_effective_defaults):
        sr = run_next([_STORE_KYOTO], next_date=_NEXT_DATE)["stores"][0]
        assert sr["drive_configured"] is False

    def test_drive_configured_false_for_empty_string(self, _patch_effective_defaults):
        sr = run_next([_STORE_MYBEAR], next_date=_NEXT_DATE)["stores"][0]
        assert sr["drive_configured"] is False

    def test_held_review_count_zero_when_no_held(self, _patch_effective_defaults):
        sr = run_next([_STORE_OSAKA], next_date=_NEXT_DATE)["stores"][0]
        assert sr["held_review_count"] == 0

    def test_held_review_count_reflects_state(self, _patch_effective_defaults):
        state_mod._STATE_FILE.write_text(json.dumps({
            "held_reviews": {
                "the_body_osaka_shinsaibashi": [
                    {"review_id": "r1", "reviewer": "A", "stars": "ONE", "comment": "x"},
                    {"review_id": "r2", "reviewer": "B", "stars": "TWO", "comment": "y"},
                ]
            }
        }))
        sr = run_next([_STORE_OSAKA], next_date=_NEXT_DATE)["stores"][0]
        assert sr["held_review_count"] == 2

    def test_no_window_time_window_ok_is_true(self, monkeypatch):
        import meo.config as cfg_mod
        monkeypatch.setattr(
            cfg_mod, "effective_defaults",
            lambda store: {"post_cadence_days": 1, "post_time_window_jst": None},
        )
        sr = run_next([_STORE_OSAKA], next_date=_NEXT_DATE)["stores"][0]
        assert sr["time_window_ok"] is True
        assert sr["time_window"] is None

    def test_store_key_and_name_populated(self, _patch_effective_defaults):
        sr = run_next([_STORE_OSAKA], next_date=_NEXT_DATE)["stores"][0]
        assert sr["store_key"] == "the_body_osaka_shinsaibashi"
        assert sr["name"] == "THE BODY 大阪 心斎橋店"


# ---------------------------------------------------------------------------
# _format_output
# ---------------------------------------------------------------------------

def _make_result(
    stores_override: list[dict] | None = None,
    next_run_date: str = "2026-08-07",
    next_run_time: str = "09:00",
) -> dict:
    default_store = {
        "store_key": "the_body_osaka_shinsaibashi",
        "name": "THE BODY 大阪 心斎橋店",
        "post_action": "post",
        "last_post": "2026-08-06",
        "cadence_days": 1,
        "next_post_due": None,
        "days_until_due": 0,
        "time_window": "06:00-23:00",
        "time_window_ok": True,
        "drive_configured": True,
        "held_review_count": 0,
    }
    return {
        "next_run_date": next_run_date,
        "next_run_time_jst": next_run_time,
        "stores": stores_override if stores_override is not None else [default_store],
    }


class TestFormatOutput:
    def test_title_in_output(self):
        out = _format_output(_make_result())
        assert "MEO Automation — 次回実行プレビュー" in out

    def test_next_run_date_in_header(self):
        out = _format_output(_make_result(next_run_date="2026-08-07"))
        assert "2026-08-07" in out

    def test_next_run_time_in_header(self):
        out = _format_output(_make_result(next_run_time="09:00"))
        assert "09:00" in out

    def test_store_name_in_output(self):
        out = _format_output(_make_result())
        assert "THE BODY 大阪 心斎橋店" in out

    def test_store_key_in_output(self):
        out = _format_output(_make_result())
        assert "the_body_osaka_shinsaibashi" in out

    def test_post_action_post_shows_checkmark(self):
        out = _format_output(_make_result())
        assert "✅ 実行予定" in out

    def test_post_action_skip_shows_skip_symbol(self):
        sr = {
            "store_key": "the_body_kyoto",
            "name": "THE BODY 京都店",
            "post_action": "skip",
            "last_post": "2026-08-07",
            "cadence_days": 2,
            "next_post_due": "2026-08-09",
            "days_until_due": 2,
            "time_window": "06:00-23:00",
            "time_window_ok": True,
            "drive_configured": True,
            "held_review_count": 0,
        }
        out = _format_output(_make_result(stores_override=[sr]))
        assert "⏭ スキップ" in out

    def test_post_action_skip_shows_next_post_due(self):
        sr = {
            "store_key": "the_body_kyoto",
            "name": "THE BODY 京都店",
            "post_action": "skip",
            "last_post": "2026-08-07",
            "cadence_days": 2,
            "next_post_due": "2026-08-09",
            "days_until_due": 2,
            "time_window": None,
            "time_window_ok": True,
            "drive_configured": True,
            "held_review_count": 0,
        }
        out = _format_output(_make_result(stores_override=[sr]))
        assert "2026-08-09" in out

    def test_post_action_skip_window_shows_time_symbol(self):
        sr = {
            "store_key": "the_body_osaka_shinsaibashi",
            "name": "THE BODY 大阪 心斎橋店",
            "post_action": "skip_window",
            "last_post": None,
            "cadence_days": 1,
            "next_post_due": None,
            "days_until_due": 0,
            "time_window": "22:00-06:00",
            "time_window_ok": False,
            "drive_configured": True,
            "held_review_count": 0,
        }
        out = _format_output(_make_result(stores_override=[sr]))
        assert "⏰ 時間帯外" in out

    def test_first_post_label_when_no_history(self):
        sr = {
            "store_key": "the_body_osaka_shinsaibashi",
            "name": "THE BODY 大阪 心斎橋店",
            "post_action": "post",
            "last_post": None,
            "cadence_days": 1,
            "next_post_due": None,
            "days_until_due": 0,
            "time_window": None,
            "time_window_ok": True,
            "drive_configured": True,
            "held_review_count": 0,
        }
        out = _format_output(_make_result(stores_override=[sr]))
        assert "初回 — 投稿履歴なし" in out

    def test_time_window_shown_when_configured(self):
        out = _format_output(_make_result())
        assert "06:00-23:00" in out

    def test_no_time_restriction_shown_when_no_window(self):
        stores_override = [{
            "store_key": "the_body_osaka_shinsaibashi",
            "name": "THE BODY 大阪 心斎橋店",
            "post_action": "post",
            "last_post": None,
            "cadence_days": 1,
            "next_post_due": None,
            "days_until_due": 0,
            "time_window": None,
            "time_window_ok": True,
            "drive_configured": True,
            "held_review_count": 0,
        }]
        out = _format_output(_make_result(stores_override=stores_override))
        assert "制限なし" in out

    def test_drive_configured_shows_checkmark(self):
        out = _format_output(_make_result())
        assert "✅ 設定済" in out

    def test_drive_not_configured_shows_warning(self):
        stores_override = [{
            "store_key": "mybear_studio_kyoto",
            "name": "MYBEAR STUDIO 京都店",
            "post_action": "post",
            "last_post": None,
            "cadence_days": 1,
            "next_post_due": None,
            "days_until_due": 0,
            "time_window": None,
            "time_window_ok": True,
            "drive_configured": False,
            "held_review_count": 0,
        }]
        out = _format_output(_make_result(stores_override=stores_override))
        assert "未設定" in out

    def test_held_reviews_count_shown(self):
        stores_override = [{
            "store_key": "the_body_osaka_shinsaibashi",
            "name": "THE BODY 大阪 心斎橋店",
            "post_action": "post",
            "last_post": None,
            "cadence_days": 1,
            "next_post_due": None,
            "days_until_due": 0,
            "time_window": None,
            "time_window_ok": True,
            "drive_configured": True,
            "held_review_count": 3,
        }]
        out = _format_output(_make_result(stores_override=stores_override))
        assert "3件" in out

    def test_no_held_reviews_shows_nashi(self):
        out = _format_output(_make_result())
        assert "✅ なし" in out

    def test_summary_line_post_count(self):
        # 2 stores, one posts, one skips
        stores_override = [
            {
                "store_key": "the_body_osaka_shinsaibashi",
                "name": "THE BODY 大阪 心斎橋店",
                "post_action": "post",
                "last_post": None, "cadence_days": 1, "next_post_due": None,
                "days_until_due": 0, "time_window": None, "time_window_ok": True,
                "drive_configured": True, "held_review_count": 0,
            },
            {
                "store_key": "the_body_kyoto",
                "name": "THE BODY 京都店",
                "post_action": "skip",
                "last_post": "2026-08-07", "cadence_days": 2,
                "next_post_due": "2026-08-09", "days_until_due": 2,
                "time_window": None, "time_window_ok": True,
                "drive_configured": True, "held_review_count": 0,
            },
        ]
        out = _format_output(_make_result(stores_override=stores_override))
        assert "1/2" in out
        assert "投稿予定" in out

    def test_summary_line_all_stores_post(self):
        stores_override = [
            {
                "store_key": k, "name": k, "post_action": "post", "last_post": None,
                "cadence_days": 1, "next_post_due": None, "days_until_due": 0,
                "time_window": None, "time_window_ok": True,
                "drive_configured": True, "held_review_count": 0,
            }
            for k in ["store_a", "store_b", "store_c"]
        ]
        out = _format_output(_make_result(stores_override=stores_override))
        assert "3/3" in out


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

class TestMain:
    def _run(self, monkeypatch, args: list[str], stores=None, defaults=None):
        import meo.config as cfg_mod
        stores = stores or [_STORE_OSAKA]
        monkeypatch.setattr(cfg_mod, "store_list", lambda: list(stores))
        if defaults is None:
            defaults = {"post_cadence_days": 1, "post_time_window_jst": None}
        monkeypatch.setattr(cfg_mod, "effective_defaults", lambda s: defaults)

        from meo.tools import next as next_mod
        with patch.object(next_mod, "sys") as mock_sys:
            mock_sys.argv = ["meo-next"] + args
            mock_sys.stderr = __import__("sys").stderr
            mock_sys.exit = __import__("sys").exit
            try:
                next_mod.main()
            except SystemExit as exc:
                return exc.code
        return 0

    def test_main_exits_0(self, monkeypatch, capsys):
        import meo.config as cfg_mod
        monkeypatch.setattr(cfg_mod, "store_list", lambda: [_STORE_OSAKA])
        monkeypatch.setattr(
            cfg_mod, "effective_defaults",
            lambda s: {"post_cadence_days": 1, "post_time_window_jst": None},
        )
        from meo.tools.next import main
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["meo-next", "--date", "2026-08-07"]):
                main()
        assert exc_info.value.code == 0

    def test_main_prints_output(self, monkeypatch, capsys):
        import meo.config as cfg_mod
        monkeypatch.setattr(cfg_mod, "store_list", lambda: [_STORE_OSAKA])
        monkeypatch.setattr(
            cfg_mod, "effective_defaults",
            lambda s: {"post_cadence_days": 1, "post_time_window_jst": None},
        )
        from meo.tools.next import main
        with pytest.raises(SystemExit):
            with patch("sys.argv", ["meo-next", "--date", "2026-08-07"]):
                main()
        out = capsys.readouterr().out
        assert "MEO Automation" in out
        assert "次回実行プレビュー" in out

    def test_main_unknown_store_exits_1(self, monkeypatch, capsys):
        import meo.config as cfg_mod
        monkeypatch.setattr(cfg_mod, "store_list", lambda: [_STORE_OSAKA])
        monkeypatch.setattr(
            cfg_mod, "effective_defaults",
            lambda s: {"post_cadence_days": 1, "post_time_window_jst": None},
        )
        from meo.tools.next import main
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["meo-next", "--store", "nonexistent_store"]):
                main()
        assert exc_info.value.code == 1

    def test_main_store_filter(self, monkeypatch, capsys):
        import meo.config as cfg_mod
        monkeypatch.setattr(cfg_mod, "store_list", lambda: list(_ALL_STORES))
        monkeypatch.setattr(
            cfg_mod, "effective_defaults",
            lambda s: {"post_cadence_days": 1, "post_time_window_jst": None},
        )
        from meo.tools.next import main
        with pytest.raises(SystemExit):
            with patch("sys.argv", ["meo-next", "--store", "the_body_kyoto",
                                    "--date", "2026-08-07"]):
                main()
        out = capsys.readouterr().out
        assert "THE BODY 京都店" in out
        assert "THE BODY 大阪" not in out

    def test_main_date_flag_used(self, monkeypatch, capsys):
        import meo.config as cfg_mod
        monkeypatch.setattr(cfg_mod, "store_list", lambda: [_STORE_OSAKA])
        monkeypatch.setattr(
            cfg_mod, "effective_defaults",
            lambda s: {"post_cadence_days": 1, "post_time_window_jst": None},
        )
        from meo.tools.next import main
        with pytest.raises(SystemExit):
            with patch("sys.argv", ["meo-next", "--date", "2026-09-01"]):
                main()
        out = capsys.readouterr().out
        assert "2026-09-01" in out

    def test_main_invalid_date_exits_1(self, monkeypatch, capsys):
        import meo.config as cfg_mod
        monkeypatch.setattr(cfg_mod, "store_list", lambda: [_STORE_OSAKA])
        monkeypatch.setattr(
            cfg_mod, "effective_defaults",
            lambda s: {"post_cadence_days": 1, "post_time_window_jst": None},
        )
        from meo.tools.next import main
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["meo-next", "--date", "not-a-date"]):
                main()
        assert exc_info.value.code == 1

    def test_main_output_file_write_error_is_nonfatal(self, monkeypatch, capsys, tmp_path):
        import meo.config as cfg_mod
        monkeypatch.setattr(cfg_mod, "store_list", lambda: [_STORE_OSAKA])
        monkeypatch.setattr(
            cfg_mod, "effective_defaults",
            lambda s: {"post_cadence_days": 1, "post_time_window_jst": None},
        )
        # Use a path whose parent cannot be created (e.g. a file acting as a dir)
        bad_parent = tmp_path / "not_a_dir.txt"
        bad_parent.write_text("i am a file")
        bad_path = bad_parent / "output.txt"
        from meo.tools.next import main
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", [
                "meo-next", "--date", "2026-08-07",
                "--output", str(bad_path),
            ]):
                main()
        # Should exit 0 (write error is non-fatal)
        assert exc_info.value.code == 0
        err = capsys.readouterr().err
        assert "Warning" in err

    def test_main_output_file_created(self, monkeypatch, capsys, tmp_path):
        import meo.config as cfg_mod
        monkeypatch.setattr(cfg_mod, "store_list", lambda: [_STORE_OSAKA])
        monkeypatch.setattr(
            cfg_mod, "effective_defaults",
            lambda s: {"post_cadence_days": 1, "post_time_window_jst": None},
        )
        output_file = tmp_path / "next_preview.txt"
        from meo.tools.next import main
        with pytest.raises(SystemExit):
            with patch("sys.argv", [
                "meo-next", "--date", "2026-08-07",
                "--output", str(output_file),
            ]):
                main()
        assert output_file.exists()
        content = output_file.read_text(encoding="utf-8")
        assert "MEO Automation" in content

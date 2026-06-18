"""Tests for meo.tools.status — operational status reporter."""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import meo.tools.status as status_mod
from meo.tools.status import _days_ago, _load_state, main


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_CONTENT_CONF = {
    "llm": {"provider": "anthropic", "model_id": "claude-haiku-4-5-20251001"},
    "defaults": {
        "post_cadence_days": 1,
        "max_post_chars": 1500,
        "max_replies_per_run": 10,
    },
}

_STORES_FULL = [
    {
        "key": "the_body_kyoto",
        "name": "THE BODY 京都店",
        "location_id": "accounts/1/locations/1",
        "drive_folder_id": "folder_abc",
        "industry": "beauty_salon",
    },
    {
        "key": "mybear_studio_kyoto",
        "name": "MYBEAR STUDIO 京都店",
        "location_id": "accounts/1/locations/2",
        "drive_folder_id": "folder_def",
        "industry": "fitness_studio",
    },
]

_STORES_TODO = [
    {
        "key": "the_body_kyoto",
        "name": "THE BODY 京都店",
        "location_id": "TODO: accounts/{account_id}/locations/{location_id}",
        "drive_folder_id": "TODO: Google Drive folder ID",
        "industry": "beauty_salon",
    },
]

_ALL_ENV = {
    "GOOGLE_CLIENT_ID": "gid",
    "GOOGLE_CLIENT_SECRET": "gsecret",
    "GOOGLE_REFRESH_TOKEN": "gtoken",
    "ANTHROPIC_API_KEY": "ak-test",
}


@pytest.fixture(autouse=True)
def _patch_cfg(monkeypatch):
    monkeypatch.setattr("meo.tools.status.cfg.store_list", lambda: _STORES_FULL)
    monkeypatch.setattr("meo.tools.status.cfg.content", lambda: _CONTENT_CONF)


@pytest.fixture()
def set_all_env(monkeypatch):
    for k, v in _ALL_ENV.items():
        monkeypatch.setenv(k, v)
    for k in ("OPENAI_API_KEY",):
        monkeypatch.delenv(k, raising=False)


# ---------------------------------------------------------------------------
# _load_state()
# ---------------------------------------------------------------------------

def test_load_state_returns_empty_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(status_mod, "_STATE_FILE", tmp_path / "state.json")
    assert _load_state() == {}


def test_load_state_returns_parsed_json(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"last_post": {"the_body_kyoto": "2026-01-10"}}), encoding="utf-8")
    monkeypatch.setattr(status_mod, "_STATE_FILE", state_file)
    result = _load_state()
    assert result["last_post"]["the_body_kyoto"] == "2026-01-10"


def test_load_state_returns_empty_on_corrupt_json(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    state_file.write_text("{bad json!!!", encoding="utf-8")
    monkeypatch.setattr(status_mod, "_STATE_FILE", state_file)
    assert _load_state() == {}


# ---------------------------------------------------------------------------
# _days_ago()
# ---------------------------------------------------------------------------

def _freeze_today(monkeypatch, iso: str):
    """Make datetime.now() inside _days_ago return a fixed JST date."""
    fixed = datetime.fromisoformat(iso + "T12:00:00+09:00")
    mock_dt = MagicMock(wraps=datetime)
    mock_dt.now.return_value = fixed
    mock_dt.fromisoformat = datetime.fromisoformat  # keep fromisoformat working
    monkeypatch.setattr(status_mod, "datetime", mock_dt)


def test_days_ago_returns_today(monkeypatch):
    _freeze_today(monkeypatch, "2026-06-18")
    assert _days_ago("2026-06-18") == "today"


def test_days_ago_returns_yesterday(monkeypatch):
    _freeze_today(monkeypatch, "2026-06-18")
    assert _days_ago("2026-06-17") == "yesterday"


def test_days_ago_returns_n_days_ago(monkeypatch):
    _freeze_today(monkeypatch, "2026-06-18")
    assert _days_ago("2026-06-10") == "8 days ago"


def test_days_ago_returns_question_mark_for_invalid_date():
    assert _days_ago("not-a-date") == "?"


def test_days_ago_returns_question_mark_for_empty_string():
    assert _days_ago("") == "?"


# ---------------------------------------------------------------------------
# main() — exit codes
# ---------------------------------------------------------------------------

def test_main_exits_0_when_all_configured_and_env_set(set_all_env, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(status_mod, "_STATE_FILE", tmp_path / "state.json")
    with patch("sys.argv", ["meo-status"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 0


def test_main_exits_1_when_env_var_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(status_mod, "_STATE_FILE", tmp_path / "state.json")
    for k in _ALL_ENV:
        monkeypatch.delenv(k, raising=False)
    with patch("sys.argv", ["meo-status"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "NOT SET" in out


def test_main_exits_1_when_store_has_todo_location_id(set_all_env, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(status_mod, "_STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("meo.tools.status.cfg.store_list", lambda: _STORES_TODO)
    with patch("sys.argv", ["meo-status"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1


def test_main_exits_1_when_only_some_stores_configured(set_all_env, tmp_path, monkeypatch, capsys):
    """One store configured, one not — should exit 1 (not fully ready)."""
    monkeypatch.setattr(status_mod, "_STATE_FILE", tmp_path / "state.json")
    mixed = [
        dict(_STORES_FULL[0]),
        dict(_STORES_FULL[0], key="store_b", name="Store B",
             location_id="TODO: pending", drive_folder_id="TODO: pending"),
    ]
    monkeypatch.setattr("meo.tools.status.cfg.store_list", lambda: mixed)
    with patch("sys.argv", ["meo-status"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1


# ---------------------------------------------------------------------------
# main() — output content
# ---------------------------------------------------------------------------

def test_main_shows_store_names(set_all_env, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(status_mod, "_STATE_FILE", tmp_path / "state.json")
    with patch("sys.argv", ["meo-status"]):
        with pytest.raises(SystemExit):
            main()
    out = capsys.readouterr().out
    assert "THE BODY 京都店" in out
    assert "MYBEAR STUDIO 京都店" in out


def test_main_shows_env_var_names(set_all_env, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(status_mod, "_STATE_FILE", tmp_path / "state.json")
    with patch("sys.argv", ["meo-status"]):
        with pytest.raises(SystemExit):
            main()
    out = capsys.readouterr().out
    assert "GOOGLE_CLIENT_ID" in out
    assert "ANTHROPIC_API_KEY" in out


def test_main_shows_never_when_no_post_recorded(set_all_env, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(status_mod, "_STATE_FILE", tmp_path / "state.json")
    with patch("sys.argv", ["meo-status"]):
        with pytest.raises(SystemExit):
            main()
    out = capsys.readouterr().out
    assert "never" in out


def test_main_shows_last_post_date_from_state(set_all_env, tmp_path, monkeypatch, capsys):
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps({"last_post": {"the_body_kyoto": "2026-06-01"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(status_mod, "_STATE_FILE", state_file)
    with patch("sys.argv", ["meo-status"]):
        with pytest.raises(SystemExit):
            main()
    out = capsys.readouterr().out
    assert "2026-06-01" in out


def test_main_shows_ready_message_when_all_good(set_all_env, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(status_mod, "_STATE_FILE", tmp_path / "state.json")
    with patch("sys.argv", ["meo-status"]):
        with pytest.raises(SystemExit):
            main()
    out = capsys.readouterr().out
    assert "dry-run" in out or "Ready" in out


def test_main_shows_state_file_not_created_when_missing(set_all_env, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(status_mod, "_STATE_FILE", tmp_path / "state.json")
    with patch("sys.argv", ["meo-status"]):
        with pytest.raises(SystemExit):
            main()
    out = capsys.readouterr().out
    assert "not yet created" in out or "state" in out.lower()


def test_main_shows_state_file_size_when_present(set_all_env, tmp_path, monkeypatch, capsys):
    state_file = tmp_path / "state.json"
    state_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(status_mod, "_STATE_FILE", state_file)
    with patch("sys.argv", ["meo-status"]):
        with pytest.raises(SystemExit):
            main()
    out = capsys.readouterr().out
    assert "bytes" in out


def test_main_never_prints_secret_values(set_all_env, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(status_mod, "_STATE_FILE", tmp_path / "state.json")
    with patch("sys.argv", ["meo-status"]):
        with pytest.raises(SystemExit):
            main()
    out = capsys.readouterr().out
    for v in _ALL_ENV.values():
        assert v not in out


def test_main_shows_llm_provider_and_model(set_all_env, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(status_mod, "_STATE_FILE", tmp_path / "state.json")
    with patch("sys.argv", ["meo-status"]):
        with pytest.raises(SystemExit):
            main()
    out = capsys.readouterr().out
    assert "anthropic" in out
    assert "claude-haiku-4-5-20251001" in out


def test_main_flags_missing_openai_key_when_provider_is_openai(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(status_mod, "_STATE_FILE", tmp_path / "state.json")
    for k, v in _ALL_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    openai_conf = dict(_CONTENT_CONF, llm={"provider": "openai", "model_id": "gpt-4o"})
    monkeypatch.setattr("meo.tools.status.cfg.content", lambda: openai_conf)
    with patch("sys.argv", ["meo-status"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "OPENAI_API_KEY" in out


def test_main_shows_partially_configured_message(set_all_env, tmp_path, monkeypatch, capsys):
    """Partial config shows a specific 'partially configured' note."""
    monkeypatch.setattr(status_mod, "_STATE_FILE", tmp_path / "state.json")
    mixed = [
        dict(_STORES_FULL[0]),
        dict(_STORES_FULL[0], key="store_b", name="Store B",
             location_id="TODO: pending", drive_folder_id="TODO: pending"),
    ]
    monkeypatch.setattr("meo.tools.status.cfg.store_list", lambda: mixed)
    with patch("sys.argv", ["meo-status"]):
        with pytest.raises(SystemExit):
            main()
    out = capsys.readouterr().out
    assert "Partially configured" in out or "partially" in out.lower()


def test_main_shows_next_step_when_no_stores_configured(set_all_env, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(status_mod, "_STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("meo.tools.status.cfg.store_list", lambda: _STORES_TODO)
    with patch("sys.argv", ["meo-status"]):
        with pytest.raises(SystemExit):
            main()
    out = capsys.readouterr().out
    assert "Next step" in out or "stores.yaml" in out

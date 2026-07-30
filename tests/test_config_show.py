"""Tests for meo.tools.config_show — effective per-store configuration display."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from meo.tools.config_show import (
    _format_banned_words,
    _format_cta_section,
    _format_defaults_section,
    _format_id_line,
    _format_llm_section,
    _format_output,
    _format_tone_section,
    main,
    run_config_show,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_STORES = [
    {
        "key": "the_body_osaka_shinsaibashi",
        "name": "THE BODY 大阪 心斎橋店",
        "location_id": "accounts/123/locations/456",
        "drive_folder_id": "folder_osaka_abc",
        "industry": "beauty_salon",
    },
    {
        "key": "the_body_kyoto",
        "name": "THE BODY 京都店",
        "location_id": "TODO: accounts/{account_id}/locations/{location_id}",
        "drive_folder_id": "TODO: Google Drive folder ID",
        "industry": "beauty_salon",
    },
    {
        "key": "mybear_studio_kyoto",
        "name": "MYBEAR STUDIO 京都店",
        "location_id": "accounts/789/locations/101",
        "drive_folder_id": "folder_mybear_xyz",
        "industry": "fitness_studio",
        "overrides": {"min_star_autoreply": 3, "post_cadence_days": 2},
    },
]

_CONTENT = {
    "defaults": {
        "language": "ja",
        "post_cadence_days": 1,
        "max_post_chars": 1500,
        "max_reply_chars": 4096,
        "max_replies_per_run": 10,
        "min_star_autoreply": 1,
        "max_review_age_days": 90,
        "post_time_window_jst": "06:00-23:00",
        "recent_post_context_count": 3,
        "recent_reply_context_count": 3,
    },
    "industry_tones": {
        "beauty_salon": {
            "tone": "温かみがあり、親しみやすく、プロフェッショナル",
            "themes": ["季節のお手入れ情報", "キャンペーン"],
        },
        "fitness_studio": {
            "tone": "元気で前向き",
            "themes": ["トレーニングのヒント", "新メニュー"],
        },
    },
    "llm": {
        "provider": "anthropic",
        "model_id": "claude-haiku-4-5-20251001",
        "temperature": 0.8,
        "max_tokens": 1024,
        "max_retries": 3,
    },
    "banned_words": ["激安", "最安値"],
}


@pytest.fixture(autouse=True)
def _patch_config(monkeypatch):
    monkeypatch.setattr("meo.tools.config_show.cfg.store_list", lambda: list(_STORES))
    monkeypatch.setattr("meo.tools.config_show.cfg.content", lambda: dict(_CONTENT))

    def _effective(store):
        base = dict(_CONTENT["defaults"])
        base.update(store.get("overrides") or {})
        return base

    monkeypatch.setattr("meo.tools.config_show.cfg.effective_defaults", _effective)


# ---------------------------------------------------------------------------
# run_config_show — data collection
# ---------------------------------------------------------------------------

def test_run_config_show_returns_all_stores():
    results = run_config_show()
    assert len(results) == 3


def test_run_config_show_store_key_and_name_present():
    results = run_config_show()
    keys = {r["store_key"] for r in results}
    assert "the_body_osaka_shinsaibashi" in keys
    assert "mybear_studio_kyoto" in keys


def test_run_config_show_filter_single_store():
    results = run_config_show(["the_body_kyoto"])
    assert len(results) == 1
    assert results[0]["store_key"] == "the_body_kyoto"


def test_run_config_show_filter_two_stores():
    results = run_config_show(["the_body_osaka_shinsaibashi", "mybear_studio_kyoto"])
    assert len(results) == 2
    keys = {r["store_key"] for r in results}
    assert "the_body_kyoto" not in keys


def test_run_config_show_unknown_key_excluded():
    results = run_config_show(["nonexistent_key"])
    assert results == []


def test_run_config_show_configured_location_id():
    results = run_config_show(["the_body_osaka_shinsaibashi"])
    r = results[0]
    assert r["location_id_configured"] is True
    assert r["location_id"] == "accounts/123/locations/456"


def test_run_config_show_todo_location_id_not_configured():
    results = run_config_show(["the_body_kyoto"])
    r = results[0]
    assert r["location_id_configured"] is False


def test_run_config_show_todo_drive_folder_not_configured():
    results = run_config_show(["the_body_kyoto"])
    r = results[0]
    assert r["drive_folder_id_configured"] is False


def test_run_config_show_configured_drive_folder():
    results = run_config_show(["the_body_osaka_shinsaibashi"])
    r = results[0]
    assert r["drive_folder_id_configured"] is True


def test_run_config_show_overrides_detected():
    results = run_config_show(["mybear_studio_kyoto"])
    r = results[0]
    assert r["overrides"] == {"min_star_autoreply": 3, "post_cadence_days": 2}


def test_run_config_show_no_overrides_empty_dict():
    results = run_config_show(["the_body_osaka_shinsaibashi"])
    r = results[0]
    assert r["overrides"] == {}


def test_run_config_show_effective_defaults_includes_overrides():
    results = run_config_show(["mybear_studio_kyoto"])
    r = results[0]
    assert r["effective_defaults"]["min_star_autoreply"] == 3
    assert r["effective_defaults"]["post_cadence_days"] == 2


def test_run_config_show_tone_profile_populated_for_beauty_salon():
    results = run_config_show(["the_body_osaka_shinsaibashi"])
    r = results[0]
    assert r["tone_profile"].get("tone") == "温かみがあり、親しみやすく、プロフェッショナル"
    assert "季節のお手入れ情報" in r["tone_profile"].get("themes", [])


def test_run_config_show_tone_profile_populated_for_fitness_studio():
    results = run_config_show(["mybear_studio_kyoto"])
    r = results[0]
    assert r["tone_profile"].get("tone") == "元気で前向き"


def test_run_config_show_unknown_industry_gives_empty_tone_profile(monkeypatch):
    stores_with_unknown = [
        {**_STORES[0], "industry": "unknown_industry", "overrides": None},
    ]
    monkeypatch.setattr("meo.tools.config_show.cfg.store_list", lambda: stores_with_unknown)
    results = run_config_show()
    assert results[0]["tone_profile"] == {}


def test_run_config_show_llm_settings_included():
    results = run_config_show(["the_body_osaka_shinsaibashi"])
    r = results[0]
    assert r["llm"]["provider"] == "anthropic"
    assert r["llm"]["model_id"] == "claude-haiku-4-5-20251001"


def test_run_config_show_banned_words_included():
    results = run_config_show(["the_body_osaka_shinsaibashi"])
    r = results[0]
    assert "激安" in r["banned_words"]


# ---------------------------------------------------------------------------
# _format_id_line
# ---------------------------------------------------------------------------

def test_format_id_line_configured_starts_with_check():
    line = _format_id_line("location_id", "accounts/123/locations/456", True)
    assert line.startswith("  ✓")
    assert "accounts/123/locations/456" in line


def test_format_id_line_not_configured_shows_warning():
    line = _format_id_line("location_id", "TODO: fill me in", False)
    assert "!" in line
    assert "未設定" in line


def test_format_id_line_long_configured_value_truncated():
    long_val = "a" * 60
    line = _format_id_line("location_id", long_val, True)
    assert "..." in line
    assert len(line) < len(long_val) + 30  # much shorter than raw value


def test_format_id_line_short_configured_value_not_truncated():
    short_val = "accounts/123/locations/456"
    line = _format_id_line("location_id", short_val, True)
    assert "..." not in line


# ---------------------------------------------------------------------------
# _format_defaults_section
# ---------------------------------------------------------------------------

def test_format_defaults_section_contains_all_fields():
    effective = dict(_CONTENT["defaults"])
    section = _format_defaults_section(effective, effective, {})
    assert "language" in section
    assert "post_cadence_days" in section
    assert "min_star_autoreply" in section
    assert "post_time_window_jst" in section


def test_format_defaults_section_override_shows_annotation():
    effective = {**_CONTENT["defaults"], "min_star_autoreply": 3}
    section = _format_defaults_section(effective, _CONTENT["defaults"], {"min_star_autoreply": 3})
    assert "← override" in section
    assert "global: 1" in section


def test_format_defaults_section_non_override_no_annotation():
    effective = dict(_CONTENT["defaults"])
    section = _format_defaults_section(effective, effective, {})
    assert "← override" not in section


def test_format_defaults_section_override_shows_overridden_value():
    effective = {**_CONTENT["defaults"], "post_cadence_days": 2}
    section = _format_defaults_section(effective, _CONTENT["defaults"], {"post_cadence_days": 2})
    assert "2" in section


def test_format_defaults_section_multiple_overrides_all_annotated():
    overrides = {"min_star_autoreply": 3, "post_cadence_days": 2}
    effective = {**_CONTENT["defaults"], **overrides}
    section = _format_defaults_section(effective, _CONTENT["defaults"], overrides)
    assert section.count("← override") == 2


# ---------------------------------------------------------------------------
# _format_tone_section
# ---------------------------------------------------------------------------

def test_format_tone_section_shows_industry_name():
    profile = _CONTENT["industry_tones"]["beauty_salon"]
    section = _format_tone_section("beauty_salon", profile)
    assert "beauty_salon" in section


def test_format_tone_section_shows_tone_description():
    profile = _CONTENT["industry_tones"]["beauty_salon"]
    section = _format_tone_section("beauty_salon", profile)
    assert "温かみがあり" in section


def test_format_tone_section_shows_themes():
    profile = _CONTENT["industry_tones"]["beauty_salon"]
    section = _format_tone_section("beauty_salon", profile)
    assert "季節のお手入れ情報" in section


def test_format_tone_section_unknown_industry_shows_warning():
    section = _format_tone_section("nonexistent", {})
    assert "未設定" in section
    assert "nonexistent" in section


# ---------------------------------------------------------------------------
# _format_llm_section
# ---------------------------------------------------------------------------

def test_format_llm_section_shows_provider_and_model():
    section = _format_llm_section(_CONTENT["llm"])
    assert "anthropic" in section
    assert "claude-haiku-4-5-20251001" in section


def test_format_llm_section_shows_temperature_and_tokens():
    section = _format_llm_section(_CONTENT["llm"])
    assert "0.8" in section
    assert "1024" in section


def test_format_llm_section_empty_dict_shows_not_configured():
    section = _format_llm_section({})
    assert "未設定" in section


def test_format_llm_section_missing_key_shows_dash():
    section = _format_llm_section({"provider": "anthropic"})
    assert "—" in section


# ---------------------------------------------------------------------------
# _format_cta_section
# ---------------------------------------------------------------------------

def test_format_cta_section_none_shows_not_configured():
    section = _format_cta_section(None)
    assert "未設定" in section


def test_format_cta_section_shows_action_type_and_url():
    cta = {"action_type": "BOOK", "url": "https://example.com/book"}
    section = _format_cta_section(cta)
    assert "BOOK" in section
    assert "https://example.com/book" in section


def test_format_cta_section_empty_url_shows_dash():
    cta = {"action_type": "LEARN_MORE", "url": ""}
    section = _format_cta_section(cta)
    assert "—" in section


# ---------------------------------------------------------------------------
# _format_banned_words
# ---------------------------------------------------------------------------

def test_format_banned_words_empty_list_shows_nashi():
    line = _format_banned_words([])
    assert "なし" in line


def test_format_banned_words_single_word():
    line = _format_banned_words(["激安"])
    assert "激安" in line


def test_format_banned_words_multiple_words_joined():
    line = _format_banned_words(["激安", "最安値", "絶対"])
    assert "激安" in line
    assert "最安値" in line
    assert "絶対" in line


# ---------------------------------------------------------------------------
# _format_output
# ---------------------------------------------------------------------------

def test_format_output_empty_results_returns_no_stores():
    output = _format_output([])
    assert "No stores found" in output


def test_format_output_contains_store_name():
    results = run_config_show(["the_body_osaka_shinsaibashi"])
    output = _format_output(results)
    assert "THE BODY 大阪 心斎橋店" in output


def test_format_output_contains_store_key():
    results = run_config_show(["the_body_osaka_shinsaibashi"])
    output = _format_output(results)
    assert "the_body_osaka_shinsaibashi" in output


def test_format_output_contains_total_line():
    results = run_config_show()
    output = _format_output(results)
    assert "合計: 3 店舗" in output


def test_format_output_contains_divider():
    results = run_config_show(["the_body_osaka_shinsaibashi"])
    output = _format_output(results)
    assert "─" in output


def test_format_output_multiple_stores_all_present():
    results = run_config_show()
    output = _format_output(results)
    assert "THE BODY 大阪 心斎橋店" in output
    assert "THE BODY 京都店" in output
    assert "MYBEAR STUDIO 京都店" in output


def test_format_output_override_annotation_appears_for_mybear():
    results = run_config_show(["mybear_studio_kyoto"])
    output = _format_output(results)
    assert "← override" in output


def test_format_output_todo_id_shows_not_configured():
    results = run_config_show(["the_body_kyoto"])
    output = _format_output(results)
    assert "未設定" in output


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def test_main_exits_0_by_default(capsys):
    with patch("sys.argv", ["meo-config-show"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 0


def test_main_prints_all_stores_by_default(capsys):
    with patch("sys.argv", ["meo-config-show"]):
        with pytest.raises(SystemExit):
            main()
    out = capsys.readouterr().out
    assert "the_body_osaka_shinsaibashi" in out
    assert "mybear_studio_kyoto" in out


def test_main_store_filter_limits_output(capsys):
    with patch("sys.argv", ["meo-config-show", "--store", "the_body_kyoto"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "the_body_kyoto" in out
    assert "the_body_osaka_shinsaibashi" not in out


def test_main_unknown_store_key_exits_1(capsys):
    with patch("sys.argv", ["meo-config-show", "--store", "no_such_store"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1


def test_main_unknown_store_key_prints_error(capsys):
    with patch("sys.argv", ["meo-config-show", "--store", "no_such_store"]):
        with pytest.raises(SystemExit):
            main()
    err = capsys.readouterr().err
    assert "no_such_store" in err

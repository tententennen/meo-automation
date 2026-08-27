"""Tests for the config validation module (meo.validator)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from meo import validator as v
from meo.tools.validate import main as validate_main


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_VALID_STORES = {
    "store_a": {
        "name": "Store A",
        "location_id": "accounts/1/locations/1",
        "drive_folder_id": "folder_1",
        "industry": "beauty_salon",
    },
}

_VALID_CONTENT = {
    "defaults": {
        "language": "ja",
        "post_cadence_days": 1,
        "max_post_chars": 1500,
        "max_reply_chars": 4096,
    },
    "industry_tones": {"beauty_salon": {"tone": "warm", "themes": ["t1"]}},
    "llm": {
        "provider": "anthropic",
        "model_id": "claude-haiku-4-5-20251001",
        "temperature": 0.8,
        "max_tokens": 1024,
    },
    "banned_words": [],
}

_FULL_ENV = {
    "GOOGLE_CLIENT_ID": "id",
    "GOOGLE_CLIENT_SECRET": "secret",
    "GOOGLE_REFRESH_TOKEN": "token",
    "ANTHROPIC_API_KEY": "key",
}


# ---------------------------------------------------------------------------
# validate_env
# ---------------------------------------------------------------------------

def test_validate_env_all_set():
    with patch.dict(os.environ, _FULL_ENV, clear=True):
        errors = v.validate_env()
    assert errors == []


def test_validate_env_missing_google_client_id():
    env = {k: v_ for k, v_ in _FULL_ENV.items() if k != "GOOGLE_CLIENT_ID"}
    with patch.dict(os.environ, env, clear=True):
        errors = v.validate_env()
    assert any("GOOGLE_CLIENT_ID" in e for e in errors)


def test_validate_env_missing_anthropic_key():
    env = {k: v_ for k, v_ in _FULL_ENV.items() if k != "ANTHROPIC_API_KEY"}
    with patch.dict(os.environ, env, clear=True):
        errors = v.validate_env()
    assert any("ANTHROPIC_API_KEY" in e for e in errors)


def test_validate_env_openai_provider_accepts_openai_key():
    env = {
        "GOOGLE_CLIENT_ID": "id",
        "GOOGLE_CLIENT_SECRET": "secret",
        "GOOGLE_REFRESH_TOKEN": "token",
        "OPENAI_API_KEY": "openai_key",
    }
    openai_content = {**_VALID_CONTENT, "llm": {"provider": "openai", "model_id": "gpt-4o-mini"}}
    with patch.dict(os.environ, env, clear=True):
        errors = v.validate_env(openai_content)
    assert errors == []


def test_validate_env_openai_provider_rejects_missing_openai_key():
    env = {
        "GOOGLE_CLIENT_ID": "id",
        "GOOGLE_CLIENT_SECRET": "secret",
        "GOOGLE_REFRESH_TOKEN": "token",
    }
    openai_content = {**_VALID_CONTENT, "llm": {"provider": "openai", "model_id": "gpt-4o-mini"}}
    with patch.dict(os.environ, env, clear=True):
        errors = v.validate_env(openai_content)
    assert any("OPENAI_API_KEY" in e for e in errors)


# ---------------------------------------------------------------------------
# validate_stores
# ---------------------------------------------------------------------------

def test_validate_stores_valid():
    assert v.validate_stores(_VALID_STORES) == []


def test_validate_stores_missing_drive_folder_id():
    stores = {
        "s": {
            "name": "S",
            "location_id": "accounts/1/locations/1",
            "industry": "beauty_salon",
            # drive_folder_id intentionally omitted
        }
    }
    errors = v.validate_stores(stores)
    assert any("drive_folder_id" in e for e in errors)


def test_validate_stores_unknown_industry():
    stores = {
        "s": {
            **_VALID_STORES["store_a"],
            "industry": "unknown_industry_xyz",
        }
    }
    errors = v.validate_stores(stores)
    assert any("unknown_industry_xyz" in e for e in errors)


def test_validate_stores_cta_valid():
    stores = {
        "s": {
            **_VALID_STORES["store_a"],
            "call_to_action": {"action_type": "BOOK", "url": "https://example.com/book"},
        }
    }
    assert v.validate_stores(stores) == []


def test_validate_stores_cta_invalid_action_type():
    stores = {
        "s": {
            **_VALID_STORES["store_a"],
            "call_to_action": {"action_type": "INVALID_TYPE", "url": "https://example.com"},
        }
    }
    errors = v.validate_stores(stores)
    assert any("INVALID_TYPE" in e for e in errors)


def test_validate_stores_cta_missing_url():
    stores = {
        "s": {
            **_VALID_STORES["store_a"],
            "call_to_action": {"action_type": "BOOK"},  # url omitted
        }
    }
    errors = v.validate_stores(stores)
    assert any("url" in e for e in errors)


def test_validate_stores_cta_empty_url_is_invalid():
    """url: '' silently disables the CTA button in posts.py — catch it here."""
    stores = {
        "s": {
            **_VALID_STORES["store_a"],
            "call_to_action": {"action_type": "BOOK", "url": ""},  # empty string
        }
    }
    errors = v.validate_stores(stores)
    assert any("url" in e for e in errors)


def test_validate_stores_cta_missing_action_type():
    stores = {
        "s": {
            **_VALID_STORES["store_a"],
            "call_to_action": {"url": "https://example.com"},  # action_type omitted
        }
    }
    errors = v.validate_stores(stores)
    assert any("action_type" in e for e in errors)


# ---------------------------------------------------------------------------
# validate_content
# ---------------------------------------------------------------------------

def test_validate_content_valid():
    assert v.validate_content(_VALID_CONTENT) == []


def test_validate_content_missing_defaults_section():
    content = {k: val for k, val in _VALID_CONTENT.items() if k != "defaults"}
    errors = v.validate_content(content)
    assert any("defaults" in e for e in errors)


def test_validate_content_missing_llm_section():
    content = {k: val for k, val in _VALID_CONTENT.items() if k != "llm"}
    errors = v.validate_content(content)
    assert any("llm" in e for e in errors)


def test_validate_content_unknown_llm_provider():
    content = {
        **_VALID_CONTENT,
        "llm": {"provider": "gemini", "model_id": "gemini-pro"},
    }
    errors = v.validate_content(content)
    assert any("gemini" in e for e in errors)


def test_validate_content_missing_industry_tones():
    content = {k: val for k, val in _VALID_CONTENT.items() if k != "industry_tones"}
    errors = v.validate_content(content)
    assert any("industry_tones" in e for e in errors)


def test_validate_content_missing_field_within_defaults():
    """When defaults is present as a dict but a required field is absent, report it."""
    content = {
        **_VALID_CONTENT,
        "defaults": {"language": "ja"},  # post_cadence_days / max_post_chars / max_reply_chars absent
    }
    errors = v.validate_content(content)
    assert any("defaults.post_cadence_days is missing" in e for e in errors)
    assert any("defaults.max_post_chars is missing" in e for e in errors)


def test_validate_content_missing_llm_provider_field():
    """When llm section exists but provider key is absent, report it."""
    content = {
        **_VALID_CONTENT,
        "llm": {"model_id": "claude-haiku-4-5-20251001"},  # provider absent
    }
    errors = v.validate_content(content)
    assert any("llm.provider is missing" in e for e in errors)


def test_validate_content_missing_llm_model_id_field():
    """When llm section exists but model_id key is absent, report it."""
    content = {
        **_VALID_CONTENT,
        "llm": {"provider": "anthropic"},  # model_id absent
    }
    errors = v.validate_content(content)
    assert any("llm.model_id is missing" in e for e in errors)


def test_validate_content_max_retries_zero_is_invalid():
    """max_retries: 0 causes _call_with_retry to run zero iterations and hit the
    safety guard — catch it at validation time with a clear error message."""
    content = {
        **_VALID_CONTENT,
        "llm": {**_VALID_CONTENT["llm"], "max_retries": 0},
    }
    errors = v.validate_content(content)
    assert any("max_retries" in e for e in errors)
    assert any(">= 1" in e for e in errors)


def test_validate_content_max_retries_negative_is_invalid():
    content = {
        **_VALID_CONTENT,
        "llm": {**_VALID_CONTENT["llm"], "max_retries": -1},
    }
    errors = v.validate_content(content)
    assert any("max_retries" in e for e in errors)


def test_validate_content_max_retries_one_is_valid():
    """min allowed value: exactly 1 (no retry, just one attempt)."""
    content = {
        **_VALID_CONTENT,
        "llm": {**_VALID_CONTENT["llm"], "max_retries": 1},
    }
    assert v.validate_content(content) == []


def test_validate_content_max_retries_absent_uses_runtime_default():
    """Omitting max_retries is valid — the default of 3 is applied at runtime."""
    content = {
        **_VALID_CONTENT,
        "llm": {k: val for k, val in _VALID_CONTENT["llm"].items() if k != "max_retries"},
    }
    assert v.validate_content(content) == []


def test_validate_content_banned_words_as_string_is_invalid():
    """banned_words must be a list.

    A bare string (e.g. banned_words: "激安") would be iterated character-by-
    character in content.py — _check_banned_words() would match single kanji
    that appear in almost every Japanese text, producing spurious warnings on
    every generated post.  Catch the misconfiguration at startup.
    """
    content = {**_VALID_CONTENT, "banned_words": "激安"}
    errors = v.validate_content(content)
    assert any("banned_words" in e for e in errors)
    assert any("list" in e for e in errors)


def test_validate_content_banned_words_absent_is_valid():
    """banned_words is optional — its absence must not cause an error."""
    content = {k: val for k, val in _VALID_CONTENT.items() if k != "banned_words"}
    assert v.validate_content(content) == []


def test_validate_content_banned_words_as_dict_is_invalid():
    """Any non-list value (dict, int, bool) must be rejected."""
    content = {**_VALID_CONTENT, "banned_words": {"word": "激安"}}
    errors = v.validate_content(content)
    assert any("banned_words" in e for e in errors)


def test_validate_content_recent_post_context_count_negative_is_invalid():
    """recent_post_context_count must be >= 0; a negative value must be rejected."""
    content = {
        **_VALID_CONTENT,
        "defaults": {**_VALID_CONTENT["defaults"], "recent_post_context_count": -1},
    }
    errors = v.validate_content(content)
    assert any("recent_post_context_count" in e for e in errors)


def test_validate_content_recent_post_context_count_zero_is_valid():
    """recent_post_context_count=0 (disable context injection) must be accepted."""
    content = {
        **_VALID_CONTENT,
        "defaults": {**_VALID_CONTENT["defaults"], "recent_post_context_count": 0},
    }
    assert v.validate_content(content) == []


def test_validate_content_recent_post_context_count_absent_is_valid():
    """recent_post_context_count is optional; its absence must not cause an error."""
    assert v.validate_content(_VALID_CONTENT) == []


def test_validate_content_recent_post_context_count_float_is_invalid():
    """A float value (e.g. 2.5) must be rejected — only integers are accepted."""
    content = {
        **_VALID_CONTENT,
        "defaults": {**_VALID_CONTENT["defaults"], "recent_post_context_count": 2.5},
    }
    errors = v.validate_content(content)
    assert any("recent_post_context_count" in e for e in errors)


def test_validate_content_recent_reply_context_count_negative_is_invalid():
    """recent_reply_context_count must be >= 0; a negative value must be rejected."""
    content = {
        **_VALID_CONTENT,
        "defaults": {**_VALID_CONTENT["defaults"], "recent_reply_context_count": -1},
    }
    errors = v.validate_content(content)
    assert any("recent_reply_context_count" in e for e in errors)


def test_validate_content_recent_reply_context_count_zero_is_valid():
    """recent_reply_context_count=0 (disable reply context injection) must be accepted."""
    content = {
        **_VALID_CONTENT,
        "defaults": {**_VALID_CONTENT["defaults"], "recent_reply_context_count": 0},
    }
    assert v.validate_content(content) == []


def test_validate_content_recent_reply_context_count_absent_is_valid():
    """recent_reply_context_count is optional; its absence must not cause an error."""
    assert v.validate_content(_VALID_CONTENT) == []


def test_validate_content_recent_reply_context_count_float_is_invalid():
    """A float value (e.g. 2.5) must be rejected — only integers are accepted."""
    content = {
        **_VALID_CONTENT,
        "defaults": {**_VALID_CONTENT["defaults"], "recent_reply_context_count": 2.5},
    }
    errors = v.validate_content(content)
    assert any("recent_reply_context_count" in e for e in errors)


# ---------------------------------------------------------------------------
# validate_all
# ---------------------------------------------------------------------------

def test_validate_all_no_errors():
    with patch("meo.validator.cfg.stores", return_value=_VALID_STORES), \
         patch("meo.validator.cfg.content", return_value=_VALID_CONTENT), \
         patch.dict(os.environ, _FULL_ENV, clear=True):
        errors = v.validate_all()
    assert errors == []


def test_validate_all_without_env_check():
    with patch("meo.validator.cfg.stores", return_value=_VALID_STORES), \
         patch("meo.validator.cfg.content", return_value=_VALID_CONTENT):
        errors = v.validate_all(check_env=False)
    assert errors == []


def test_validate_all_handles_stores_load_failure():
    with patch("meo.validator.cfg.stores", side_effect=Exception("YAML parse error")), \
         patch("meo.validator.cfg.content", return_value=_VALID_CONTENT), \
         patch.dict(os.environ, _FULL_ENV, clear=True):
        errors = v.validate_all()
    assert any("stores.yaml" in e and "failed to load" in e for e in errors)


def test_validate_all_handles_content_load_failure():
    with patch("meo.validator.cfg.stores", return_value=_VALID_STORES), \
         patch("meo.validator.cfg.content", side_effect=FileNotFoundError("not found")), \
         patch.dict(os.environ, _FULL_ENV, clear=True):
        errors = v.validate_all()
    assert any("content.yaml" in e and "failed to load" in e for e in errors)


def test_validate_all_collects_errors_from_multiple_sources():
    bad_stores = {
        "s": {
            "name": "S",
            # location_id and drive_folder_id missing, unknown industry
            "industry": "unknown_xyz",
        }
    }
    with patch("meo.validator.cfg.stores", return_value=bad_stores), \
         patch("meo.validator.cfg.content", return_value=_VALID_CONTENT), \
         patch.dict(os.environ, _FULL_ENV, clear=True):
        errors = v.validate_all()
    assert len(errors) >= 3


# ---------------------------------------------------------------------------
# Per-store override key validation
# ---------------------------------------------------------------------------

def test_validate_stores_valid_override_keys_pass():
    stores = {
        "s": {
            **_VALID_STORES["store_a"],
            "overrides": {"post_cadence_days": 2, "min_star_autoreply": 3},
        }
    }
    assert v.validate_stores(stores) == []


def test_validate_stores_unknown_override_key_produces_error():
    stores = {
        "s": {
            **_VALID_STORES["store_a"],
            "overrides": {"post_cadence_days": 2, "invalid_setting": True},
        }
    }
    errors = v.validate_stores(stores)
    assert any("invalid_setting" in e for e in errors)
    assert any("overrides" in e for e in errors)


def test_validate_stores_max_review_age_days_is_a_valid_override_key():
    stores = {
        "s": {
            **_VALID_STORES["store_a"],
            "overrides": {"max_review_age_days": 30},
        }
    }
    assert v.validate_stores(stores) == []


# ---------------------------------------------------------------------------
# meo-validate CLI (tools/validate.py main())
# ---------------------------------------------------------------------------

def test_main_exits_0_when_config_and_env_are_valid(capsys):
    with patch("meo.validator.cfg.stores", return_value=_VALID_STORES), \
         patch("meo.validator.cfg.content", return_value=_VALID_CONTENT), \
         patch.dict(os.environ, _FULL_ENV, clear=True), \
         patch("sys.argv", ["meo-validate"]), \
         pytest.raises(SystemExit) as exc_info:
        validate_main()
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "OK" in out
    assert "config + environment" in out


def test_main_exits_1_when_env_vars_are_missing(capsys):
    with patch("meo.validator.cfg.stores", return_value=_VALID_STORES), \
         patch("meo.validator.cfg.content", return_value=_VALID_CONTENT), \
         patch.dict(os.environ, {}, clear=True), \
         patch("sys.argv", ["meo-validate"]), \
         pytest.raises(SystemExit) as exc_info:
        validate_main()
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "FAILED" in out


def test_main_no_env_skips_credential_check(capsys):
    """--no-env passes even with no credentials set, if config is valid."""
    with patch("meo.validator.cfg.stores", return_value=_VALID_STORES), \
         patch("meo.validator.cfg.content", return_value=_VALID_CONTENT), \
         patch.dict(os.environ, {}, clear=True), \
         patch("sys.argv", ["meo-validate", "--no-env"]), \
         pytest.raises(SystemExit) as exc_info:
        validate_main()
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "OK" in out
    assert "config structure" in out


def test_main_no_env_still_catches_config_errors(capsys):
    """--no-env does not hide structural errors in the YAML config files."""
    bad_content = {k: val for k, val in _VALID_CONTENT.items() if k != "llm"}
    with patch("meo.validator.cfg.stores", return_value=_VALID_STORES), \
         patch("meo.validator.cfg.content", return_value=bad_content), \
         patch.dict(os.environ, {}, clear=True), \
         patch("sys.argv", ["meo-validate", "--no-env"]), \
         pytest.raises(SystemExit) as exc_info:
        validate_main()
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "FAILED" in out
    assert "llm" in out


# ---------------------------------------------------------------------------
# validate_content — post_time_window_jst
# ---------------------------------------------------------------------------

def _content_with_window(window):
    """Return a content dict with post_time_window_jst set to the given value."""
    import copy
    data = copy.deepcopy(_VALID_CONTENT)
    data["defaults"]["post_time_window_jst"] = window
    return data


def test_validate_content_post_time_window_jst_absent_is_valid():
    """post_time_window_jst is optional — omitting it must not produce errors."""
    errors = v.validate_content(_VALID_CONTENT)
    assert errors == []


def test_validate_content_post_time_window_jst_valid_format():
    errors = v.validate_content(_content_with_window("06:00-23:00"))
    assert errors == []


def test_validate_content_post_time_window_jst_midnight_crossing_valid():
    errors = v.validate_content(_content_with_window("22:00-06:00"))
    assert errors == []


def test_validate_content_post_time_window_jst_bad_format_no_leading_zeros():
    errors = v.validate_content(_content_with_window("6:0-23:0"))
    assert any("post_time_window_jst" in e for e in errors)
    assert any("HH:MM-HH:MM" in e for e in errors)


def test_validate_content_post_time_window_jst_bad_format_no_dash():
    errors = v.validate_content(_content_with_window("0600-2300"))
    assert any("post_time_window_jst" in e for e in errors)


def test_validate_content_post_time_window_jst_non_string_is_invalid():
    errors = v.validate_content(_content_with_window(600))
    assert any("post_time_window_jst" in e for e in errors)


def test_validate_content_post_time_window_jst_out_of_range_hour():
    errors = v.validate_content(_content_with_window("25:00-23:00"))
    assert any("post_time_window_jst" in e for e in errors)
    assert any("out-of-range" in e for e in errors)


def test_validate_content_post_time_window_jst_out_of_range_minute():
    errors = v.validate_content(_content_with_window("06:60-23:00"))
    assert any("post_time_window_jst" in e for e in errors)
    assert any("out-of-range" in e for e in errors)


def test_validate_stores_override_post_time_window_jst_is_allowed():
    """post_time_window_jst is accepted as a per-store override key."""
    stores = {
        "store_a": {
            **_VALID_STORES["store_a"],
            "overrides": {"post_time_window_jst": "08:00-21:00"},
        }
    }
    errors = v.validate_stores(stores)
    assert errors == []


# ---------------------------------------------------------------------------
# validate_content — max_drive_image_bytes
# ---------------------------------------------------------------------------

def _content_with_max_image_bytes(value):
    base = _VALID_CONTENT.copy()
    base["defaults"] = {**base["defaults"], "max_drive_image_bytes": value}
    return base


def test_validate_content_max_drive_image_bytes_absent_is_valid():
    """max_drive_image_bytes is optional; omitting it is valid."""
    errors = v.validate_content(_VALID_CONTENT)
    assert not any("max_drive_image_bytes" in e for e in errors)


def test_validate_content_max_drive_image_bytes_positive_integer_is_valid():
    errors = v.validate_content(_content_with_max_image_bytes(5_242_880))
    assert not any("max_drive_image_bytes" in e for e in errors)


def test_validate_content_max_drive_image_bytes_zero_is_invalid():
    errors = v.validate_content(_content_with_max_image_bytes(0))
    assert any("max_drive_image_bytes" in e for e in errors)


def test_validate_content_max_drive_image_bytes_negative_is_invalid():
    errors = v.validate_content(_content_with_max_image_bytes(-1))
    assert any("max_drive_image_bytes" in e for e in errors)


def test_validate_content_max_drive_image_bytes_float_is_invalid():
    errors = v.validate_content(_content_with_max_image_bytes(5.5))
    assert any("max_drive_image_bytes" in e for e in errors)


# ---------------------------------------------------------------------------
# validate_stores — max_drive_image_bytes override
# ---------------------------------------------------------------------------

def test_validate_stores_max_drive_image_bytes_is_allowed_override():
    """max_drive_image_bytes is accepted as a per-store override key."""
    stores = {
        "store_a": {
            **_VALID_STORES["store_a"],
            "overrides": {"max_drive_image_bytes": 2_000_000},
        }
    }
    errors = v.validate_stores(stores)
    assert errors == []


# ---------------------------------------------------------------------------
# validate_content — max_banned_retries
# ---------------------------------------------------------------------------

def _content_with_max_banned_retries(value):
    base = _VALID_CONTENT.copy()
    base["defaults"] = {**base["defaults"], "max_banned_retries": value}
    return base


def test_validate_content_max_banned_retries_absent_is_valid():
    """max_banned_retries is optional; omitting it is valid (defaults to 2)."""
    errors = v.validate_content(_VALID_CONTENT)
    assert not any("max_banned_retries" in e for e in errors)


def test_validate_content_max_banned_retries_positive_is_valid():
    errors = v.validate_content(_content_with_max_banned_retries(2))
    assert not any("max_banned_retries" in e for e in errors)


def test_validate_content_max_banned_retries_zero_is_valid():
    """0 is allowed — means 'warn but do not retry'."""
    errors = v.validate_content(_content_with_max_banned_retries(0))
    assert not any("max_banned_retries" in e for e in errors)


def test_validate_content_max_banned_retries_negative_is_invalid():
    errors = v.validate_content(_content_with_max_banned_retries(-1))
    assert any("max_banned_retries" in e for e in errors)


def test_validate_content_max_banned_retries_float_is_invalid():
    errors = v.validate_content(_content_with_max_banned_retries(1.5))
    assert any("max_banned_retries" in e for e in errors)


# ---------------------------------------------------------------------------
# validate_stores — max_banned_retries override
# ---------------------------------------------------------------------------

def test_validate_stores_max_banned_retries_is_allowed_override():
    """max_banned_retries is accepted as a per-store override key."""
    stores = {
        "store_a": {
            **_VALID_STORES["store_a"],
            "overrides": {"max_banned_retries": 0},
        }
    }
    errors = v.validate_stores(stores)
    assert errors == []

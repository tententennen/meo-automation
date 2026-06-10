"""Tests for the config validation module (meo.validator)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from meo import validator as v


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

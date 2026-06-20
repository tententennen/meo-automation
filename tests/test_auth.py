"""Tests for meo.auth — get_credentials() and _require_env()."""
import os
import pytest
from unittest.mock import MagicMock, patch

from meo.auth import get_credentials, _require_env


# ---------------------------------------------------------------------------
# _require_env
# ---------------------------------------------------------------------------

def test_require_env_returns_value_when_set(monkeypatch):
    monkeypatch.setenv("MEO_TEST_VAR", "hello")
    assert _require_env("MEO_TEST_VAR") == "hello"


def test_require_env_raises_when_missing():
    os.environ.pop("MEO_TEST_VAR_MISSING", None)
    with pytest.raises(EnvironmentError, match="MEO_TEST_VAR_MISSING"):
        _require_env("MEO_TEST_VAR_MISSING")


def test_require_env_raises_when_empty_string(monkeypatch):
    monkeypatch.setenv("MEO_TEST_EMPTY", "")
    with pytest.raises(EnvironmentError, match="MEO_TEST_EMPTY"):
        _require_env("MEO_TEST_EMPTY")


# ---------------------------------------------------------------------------
# get_credentials
# ---------------------------------------------------------------------------

def _set_google_env(monkeypatch, *, client_id="cid", client_secret="csec", refresh_token="rtok"):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", client_id)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", client_secret)
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", refresh_token)


def test_get_credentials_raises_when_client_id_missing(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_REFRESH_TOKEN", raising=False)
    with pytest.raises(EnvironmentError, match="GOOGLE_CLIENT_ID"):
        get_credentials()


def test_get_credentials_raises_when_client_secret_missing(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_REFRESH_TOKEN", raising=False)
    with pytest.raises(EnvironmentError, match="GOOGLE_CLIENT_SECRET"):
        get_credentials()


def test_get_credentials_raises_when_refresh_token_missing(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csec")
    monkeypatch.delenv("GOOGLE_REFRESH_TOKEN", raising=False)
    with pytest.raises(EnvironmentError, match="GOOGLE_REFRESH_TOKEN"):
        get_credentials()


def test_get_credentials_returns_credentials_object(monkeypatch):
    _set_google_env(monkeypatch)
    mock_creds = MagicMock()
    with patch("meo.auth.Credentials", return_value=mock_creds), \
         patch("meo.auth.Request"):
        result = get_credentials()
    assert result is mock_creds


def test_get_credentials_builds_credentials_with_env_values(monkeypatch):
    _set_google_env(monkeypatch, client_id="my_id", client_secret="my_sec", refresh_token="my_tok")
    mock_creds = MagicMock()
    with patch("meo.auth.Credentials", return_value=mock_creds) as mock_cls, \
         patch("meo.auth.Request"):
        get_credentials()
    _, kwargs = mock_cls.call_args
    assert kwargs["client_id"] == "my_id"
    assert kwargs["client_secret"] == "my_sec"
    assert kwargs["refresh_token"] == "my_tok"
    assert kwargs["token"] is None


def test_get_credentials_calls_refresh(monkeypatch):
    _set_google_env(monkeypatch)
    mock_creds = MagicMock()
    mock_request_instance = MagicMock()
    with patch("meo.auth.Credentials", return_value=mock_creds), \
         patch("meo.auth.Request", return_value=mock_request_instance):
        get_credentials()
    mock_creds.refresh.assert_called_once_with(mock_request_instance)


def test_get_credentials_includes_both_scopes(monkeypatch):
    _set_google_env(monkeypatch)
    mock_creds = MagicMock()
    with patch("meo.auth.Credentials", return_value=mock_creds) as mock_cls, \
         patch("meo.auth.Request"):
        get_credentials()
    _, kwargs = mock_cls.call_args
    scopes = kwargs["scopes"]
    assert "https://www.googleapis.com/auth/business.manage" in scopes
    assert "https://www.googleapis.com/auth/drive.readonly" in scopes

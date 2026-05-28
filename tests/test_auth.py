"""Tests for meo.auth — credential building from environment variables."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from meo import auth


def test_require_env_returns_value(monkeypatch):
    monkeypatch.setenv("TEST_VAR_MEO", "hello")
    assert auth._require_env("TEST_VAR_MEO") == "hello"


def test_require_env_raises_when_missing(monkeypatch):
    monkeypatch.delenv("TEST_VAR_MEO", raising=False)
    with pytest.raises(EnvironmentError, match="TEST_VAR_MEO"):
        auth._require_env("TEST_VAR_MEO")


def test_require_env_raises_when_empty(monkeypatch):
    monkeypatch.setenv("TEST_VAR_MEO", "")
    with pytest.raises(EnvironmentError, match="TEST_VAR_MEO"):
        auth._require_env("TEST_VAR_MEO")


def test_get_credentials_raises_missing_client_id(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "token")
    with pytest.raises(EnvironmentError, match="GOOGLE_CLIENT_ID"):
        auth.get_credentials()


def test_get_credentials_raises_missing_client_secret(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client_id")
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "token")
    with pytest.raises(EnvironmentError, match="GOOGLE_CLIENT_SECRET"):
        auth.get_credentials()


def test_get_credentials_raises_missing_refresh_token(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client_id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.delenv("GOOGLE_REFRESH_TOKEN", raising=False)
    with pytest.raises(EnvironmentError, match="GOOGLE_REFRESH_TOKEN"):
        auth.get_credentials()


def test_get_credentials_builds_and_refreshes(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "rtoken")

    mock_creds = MagicMock()
    mock_request_cls = MagicMock()

    with (
        patch("meo.auth.Credentials", return_value=mock_creds) as mock_creds_cls,
        patch("meo.auth.Request", mock_request_cls),
    ):
        result = auth.get_credentials()

    mock_creds_cls.assert_called_once_with(
        token=None,
        refresh_token="rtoken",
        token_uri=auth._TOKEN_URI,
        client_id="cid",
        client_secret="csecret",
        scopes=auth.SCOPES,
    )
    mock_creds.refresh.assert_called_once()
    assert result is mock_creds


def test_scopes_include_business_manage():
    assert "https://www.googleapis.com/auth/business.manage" in auth.SCOPES


def test_scopes_include_drive_readonly():
    assert "https://www.googleapis.com/auth/drive.readonly" in auth.SCOPES

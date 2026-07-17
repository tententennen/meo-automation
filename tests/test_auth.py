"""Tests for meo.auth — get_credentials(), _require_env(), and run_auth_flow()."""
import os
import pytest
from unittest.mock import MagicMock, patch

from meo.auth import get_credentials, _require_env, run_auth_flow


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


# ---------------------------------------------------------------------------
# run_auth_flow
# ---------------------------------------------------------------------------

def _make_flow_mock(refresh_token: str = "rt_test_token") -> tuple[MagicMock, MagicMock]:
    """Return (mock_flow_class, mock_creds) for patching InstalledAppFlow."""
    mock_creds = MagicMock()
    mock_creds.refresh_token = refresh_token
    mock_flow_instance = MagicMock()
    mock_flow_instance.run_local_server.return_value = mock_creds
    mock_flow_class = MagicMock()
    mock_flow_class.from_client_config.return_value = mock_flow_instance
    return mock_flow_class, mock_creds


def test_run_auth_flow_prints_refresh_token(monkeypatch, capsys):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test_client_id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test_client_secret")
    mock_flow_class, _ = _make_flow_mock("rt_printed_token")
    with patch("google_auth_oauthlib.flow.InstalledAppFlow", mock_flow_class):
        run_auth_flow()
    out = capsys.readouterr().out
    assert "rt_printed_token" in out
    assert "GOOGLE_REFRESH_TOKEN" in out


def test_run_auth_flow_passes_both_scopes(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csec")
    mock_flow_class, _ = _make_flow_mock()
    with patch("google_auth_oauthlib.flow.InstalledAppFlow", mock_flow_class):
        run_auth_flow()
    _, kwargs = mock_flow_class.from_client_config.call_args
    scopes = kwargs["scopes"]
    assert "https://www.googleapis.com/auth/business.manage" in scopes
    assert "https://www.googleapis.com/auth/drive.readonly" in scopes


def test_run_auth_flow_uses_client_id_and_secret_from_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "my_client_id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "my_client_secret")
    mock_flow_class, _ = _make_flow_mock()
    with patch("google_auth_oauthlib.flow.InstalledAppFlow", mock_flow_class):
        run_auth_flow()
    args, kwargs = mock_flow_class.from_client_config.call_args
    client_config = args[0]
    assert client_config["installed"]["client_id"] == "my_client_id"
    assert client_config["installed"]["client_secret"] == "my_client_secret"


def test_run_auth_flow_raises_when_client_id_missing(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csec")
    with pytest.raises(EnvironmentError, match="GOOGLE_CLIENT_ID"):
        run_auth_flow()


def test_run_auth_flow_raises_when_client_secret_missing(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    with pytest.raises(EnvironmentError, match="GOOGLE_CLIENT_SECRET"):
        run_auth_flow()


def test_run_auth_flow_calls_run_local_server_with_port_0(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csec")
    mock_flow_class, _ = _make_flow_mock()
    mock_flow_instance = mock_flow_class.from_client_config.return_value
    with patch("google_auth_oauthlib.flow.InstalledAppFlow", mock_flow_class):
        run_auth_flow()
    mock_flow_instance.run_local_server.assert_called_once_with(port=0)

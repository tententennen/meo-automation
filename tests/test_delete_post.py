"""Tests for meo-delete-post — fully mocked, no Google credentials needed."""

from unittest.mock import MagicMock, call, patch
import pytest
import requests

from meo.tools.delete_post import (
    _validate_post_name,
    _format_post_preview,
    _parse_create_time,
    _prompt_confirm,
    run_delete_post,
    main,
)


# ---------------------------------------------------------------------------
# Shared fixtures / constants
# ---------------------------------------------------------------------------

_POST_NAME = "accounts/1/locations/2/localPosts/42"

_POST_DATA = {
    "name": _POST_NAME,
    "summary": "春の特別キャンペーン開催中！お得なプランをご用意しています。",
    "topicType": "STANDARD",
    "state": "LIVE",
    "createTime": "2026-04-01T02:00:00Z",
    "updateTime": "2026-04-01T02:01:00Z",
}


def _make_gbp(*, delete_raises=None, get_raises=None):
    gbp = MagicMock()
    if delete_raises:
        gbp.delete_local_post.side_effect = delete_raises
    if get_raises:
        gbp.get_local_post.side_effect = get_raises
    else:
        gbp.get_local_post.return_value = _POST_DATA
    return gbp


def _http_error(status_code: int = 404) -> requests.HTTPError:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    return requests.HTTPError(f"{status_code} Error", response=resp)


# ---------------------------------------------------------------------------
# _validate_post_name
# ---------------------------------------------------------------------------

def test_validate_post_name_valid():
    _validate_post_name("accounts/123/locations/456/localPosts/789")  # must not raise


def test_validate_post_name_valid_with_long_ids():
    _validate_post_name("accounts/999999999/locations/888888888/localPosts/AbCdEfGhIj")


def test_validate_post_name_missing_localPosts_segment():
    with pytest.raises(ValueError, match="/localPosts/"):
        _validate_post_name("accounts/1/locations/2")


def test_validate_post_name_empty_string():
    with pytest.raises(ValueError, match="/localPosts/"):
        _validate_post_name("")


def test_validate_post_name_wrong_resource_type():
    with pytest.raises(ValueError, match="/localPosts/"):
        _validate_post_name("accounts/1/locations/2/reviews/99")


def test_validate_post_name_just_id():
    with pytest.raises(ValueError, match="/localPosts/"):
        _validate_post_name("localPosts/789")


# ---------------------------------------------------------------------------
# _parse_create_time
# ---------------------------------------------------------------------------

def test_parse_create_time_utc_z():
    result = _parse_create_time("2026-04-01T02:00:00Z")
    assert "2026-04-01" in result
    assert "JST" in result


def test_parse_create_time_with_offset():
    result = _parse_create_time("2026-04-01T02:00:00+00:00")
    assert "2026-04-01" in result


def test_parse_create_time_invalid_falls_back():
    result = _parse_create_time("not-a-date")
    assert result == "not-a-date"


def test_parse_create_time_empty_falls_back():
    result = _parse_create_time("")
    assert result == ""


# ---------------------------------------------------------------------------
# _format_post_preview
# ---------------------------------------------------------------------------

def test_format_post_preview_includes_name():
    output = _format_post_preview(_POST_DATA)
    assert _POST_NAME in output


def test_format_post_preview_includes_state():
    output = _format_post_preview(_POST_DATA)
    assert "LIVE" in output


def test_format_post_preview_includes_type():
    output = _format_post_preview(_POST_DATA)
    assert "STANDARD" in output


def test_format_post_preview_includes_summary_preview():
    output = _format_post_preview(_POST_DATA)
    assert "春の特別キャンペーン" in output


def test_format_post_preview_truncates_long_summary():
    long_post = dict(_POST_DATA, summary="あ" * 200)
    output = _format_post_preview(long_post)
    assert "…" in output


def test_format_post_preview_no_summary():
    output = _format_post_preview({**_POST_DATA, "summary": ""})
    assert _POST_NAME in output


def test_format_post_preview_no_create_time():
    output = _format_post_preview({**_POST_DATA, "createTime": ""})
    assert _POST_NAME in output


# ---------------------------------------------------------------------------
# run_delete_post — dry_run
# ---------------------------------------------------------------------------

def test_run_delete_post_dry_run_returns_dry_run_status():
    gbp = _make_gbp()
    result = run_delete_post(_POST_NAME, gbp, dry_run=True)
    assert result["status"] == "dry_run"
    assert result["post_name"] == _POST_NAME


def test_run_delete_post_dry_run_does_not_call_api():
    gbp = _make_gbp()
    run_delete_post(_POST_NAME, gbp, dry_run=True)
    gbp.delete_local_post.assert_not_called()


# ---------------------------------------------------------------------------
# run_delete_post — live deletion
# ---------------------------------------------------------------------------

def test_run_delete_post_live_returns_deleted_status():
    gbp = _make_gbp()
    result = run_delete_post(_POST_NAME, gbp, dry_run=False)
    assert result["status"] == "deleted"
    assert result["post_name"] == _POST_NAME


def test_run_delete_post_live_calls_api_with_correct_name():
    gbp = _make_gbp()
    run_delete_post(_POST_NAME, gbp, dry_run=False)
    gbp.delete_local_post.assert_called_once_with(_POST_NAME)


def test_run_delete_post_invalid_name_raises_value_error():
    gbp = _make_gbp()
    with pytest.raises(ValueError, match="/localPosts/"):
        run_delete_post("accounts/1/locations/2", gbp)


def test_run_delete_post_api_error_propagates():
    err = _http_error(404)
    gbp = _make_gbp(delete_raises=err)
    with pytest.raises(requests.HTTPError):
        run_delete_post(_POST_NAME, gbp, dry_run=False)


def test_run_delete_post_403_propagates():
    gbp = _make_gbp(delete_raises=_http_error(403))
    with pytest.raises(requests.HTTPError):
        run_delete_post(_POST_NAME, gbp, dry_run=False)


# ---------------------------------------------------------------------------
# _prompt_confirm
# ---------------------------------------------------------------------------

def test_prompt_confirm_y_returns_true(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "y")
    assert _prompt_confirm() is True


def test_prompt_confirm_yes_returns_true(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    assert _prompt_confirm() is True


def test_prompt_confirm_uppercase_yes(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "YES")
    assert _prompt_confirm() is True


def test_prompt_confirm_n_returns_false(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "n")
    assert _prompt_confirm() is False


def test_prompt_confirm_empty_returns_false(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert _prompt_confirm() is False


def test_prompt_confirm_eoferror_propagates(monkeypatch):
    def _raise(_):
        raise EOFError
    monkeypatch.setattr("builtins.input", _raise)
    with pytest.raises(EOFError):
        _prompt_confirm()


# ---------------------------------------------------------------------------
# main() — dry_run path
# ---------------------------------------------------------------------------

def test_main_dry_run_exits_0(capsys):
    with patch("sys.argv", ["meo-delete-post", "--post-name", _POST_NAME, "--dry-run"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out


def test_main_dry_run_does_not_call_credentials(capsys):
    with patch("sys.argv", ["meo-delete-post", "--post-name", _POST_NAME, "--dry-run"]):
        with patch("meo.tools.delete_post.get_credentials") as mock_creds:
            with pytest.raises(SystemExit):
                main()
        mock_creds.assert_not_called()


def test_main_dry_run_invalid_name_exits_1(capsys):
    with patch("sys.argv", ["meo-delete-post", "--post-name", "accounts/1/locations/2", "--dry-run"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1


# ---------------------------------------------------------------------------
# main() — --yes path
# ---------------------------------------------------------------------------

def test_main_yes_exits_0_on_success(capsys):
    with patch("sys.argv", ["meo-delete-post", "--post-name", _POST_NAME, "--yes"]):
        with patch("meo.tools.delete_post.get_credentials", return_value=MagicMock()):
            with patch("meo.tools.delete_post.BusinessProfileClient") as mock_gbp_cls:
                mock_gbp = MagicMock()
                mock_gbp_cls.return_value = mock_gbp
                main()  # success path returns normally (no sys.exit)
    mock_gbp.delete_local_post.assert_called_once_with(_POST_NAME)


def test_main_yes_prints_post_name_on_success(capsys):
    with patch("sys.argv", ["meo-delete-post", "--post-name", _POST_NAME, "--yes"]):
        with patch("meo.tools.delete_post.get_credentials", return_value=MagicMock()):
            with patch("meo.tools.delete_post.BusinessProfileClient") as mock_gbp_cls:
                mock_gbp_cls.return_value = MagicMock()
                main()
    out = capsys.readouterr().out
    assert _POST_NAME in out


def test_main_yes_api_error_exits_1(capsys):
    with patch("sys.argv", ["meo-delete-post", "--post-name", _POST_NAME, "--yes"]):
        with patch("meo.tools.delete_post.get_credentials", return_value=MagicMock()):
            with patch("meo.tools.delete_post.BusinessProfileClient") as mock_gbp_cls:
                mock_gbp = MagicMock()
                mock_gbp.delete_local_post.side_effect = _http_error(404)
                mock_gbp_cls.return_value = mock_gbp
                with pytest.raises(SystemExit) as exc:
                    main()
    assert exc.value.code == 1


# ---------------------------------------------------------------------------
# main() — auth error
# ---------------------------------------------------------------------------

def test_main_auth_error_exits_1(capsys):
    with patch("sys.argv", ["meo-delete-post", "--post-name", _POST_NAME, "--yes"]):
        with patch(
            "meo.tools.delete_post.get_credentials",
            side_effect=EnvironmentError("GOOGLE_REFRESH_TOKEN not set"),
        ):
            with pytest.raises(SystemExit) as exc:
                main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Authentication failed" in err


# ---------------------------------------------------------------------------
# main() — interactive confirmation path (no --yes)
# ---------------------------------------------------------------------------

def test_main_confirm_yes_deletes(capsys, monkeypatch):
    monkeypatch.setattr("meo.tools.delete_post._prompt_confirm", lambda: True)
    with patch("sys.argv", ["meo-delete-post", "--post-name", _POST_NAME]):
        with patch("meo.tools.delete_post.get_credentials", return_value=MagicMock()):
            with patch("meo.tools.delete_post.BusinessProfileClient") as mock_gbp_cls:
                mock_gbp = MagicMock()
                mock_gbp.get_local_post.return_value = _POST_DATA
                mock_gbp_cls.return_value = mock_gbp
                main()  # success path returns normally
    mock_gbp.delete_local_post.assert_called_once_with(_POST_NAME)


def test_main_confirm_no_cancels(capsys, monkeypatch):
    monkeypatch.setattr("meo.tools.delete_post._prompt_confirm", lambda: False)
    with patch("sys.argv", ["meo-delete-post", "--post-name", _POST_NAME]):
        with patch("meo.tools.delete_post.get_credentials", return_value=MagicMock()):
            with patch("meo.tools.delete_post.BusinessProfileClient") as mock_gbp_cls:
                mock_gbp = MagicMock()
                mock_gbp.get_local_post.return_value = _POST_DATA
                mock_gbp_cls.return_value = mock_gbp
                with pytest.raises(SystemExit) as exc:
                    main()
    assert exc.value.code == 0
    mock_gbp.delete_local_post.assert_not_called()


def test_main_non_interactive_eoferror_exits_1(capsys, monkeypatch):
    def _raise():
        raise EOFError
    monkeypatch.setattr("meo.tools.delete_post._prompt_confirm", _raise)
    with patch("sys.argv", ["meo-delete-post", "--post-name", _POST_NAME]):
        with patch("meo.tools.delete_post.get_credentials", return_value=MagicMock()):
            with patch("meo.tools.delete_post.BusinessProfileClient") as mock_gbp_cls:
                mock_gbp = MagicMock()
                mock_gbp.get_local_post.return_value = _POST_DATA
                mock_gbp_cls.return_value = mock_gbp
                with pytest.raises(SystemExit) as exc:
                    main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "--yes" in err


def test_main_preview_fetch_failure_still_prompts(capsys, monkeypatch):
    monkeypatch.setattr("meo.tools.delete_post._prompt_confirm", lambda: False)
    with patch("sys.argv", ["meo-delete-post", "--post-name", _POST_NAME]):
        with patch("meo.tools.delete_post.get_credentials", return_value=MagicMock()):
            with patch("meo.tools.delete_post.BusinessProfileClient") as mock_gbp_cls:
                mock_gbp = MagicMock()
                mock_gbp.get_local_post.side_effect = _http_error(404)
                mock_gbp_cls.return_value = mock_gbp
                with pytest.raises(SystemExit) as exc:
                    main()
    # Cancelled (no is default), not an error
    assert exc.value.code == 0


def test_main_confirm_shows_post_preview(capsys, monkeypatch):
    monkeypatch.setattr("meo.tools.delete_post._prompt_confirm", lambda: False)
    with patch("sys.argv", ["meo-delete-post", "--post-name", _POST_NAME]):
        with patch("meo.tools.delete_post.get_credentials", return_value=MagicMock()):
            with patch("meo.tools.delete_post.BusinessProfileClient") as mock_gbp_cls:
                mock_gbp = MagicMock()
                mock_gbp.get_local_post.return_value = _POST_DATA
                mock_gbp_cls.return_value = mock_gbp
                with pytest.raises(SystemExit):
                    main()
    out = capsys.readouterr().out
    assert "LIVE" in out or _POST_NAME in out


# ---------------------------------------------------------------------------
# BusinessProfileClient — get_local_post and delete_local_post (integration)
# ---------------------------------------------------------------------------

def _ok_resp(body: dict):
    resp = MagicMock()
    resp.ok = True
    resp.raise_for_status.return_value = None
    resp.json.return_value = body
    return resp


def _err_resp(status_code: int):
    resp = MagicMock()
    resp.ok = False
    resp.status_code = status_code
    resp.json.return_value = {"error": {"message": "not found"}}
    err = requests.HTTPError(f"{status_code} Error", response=resp)
    resp.raise_for_status.side_effect = err
    return resp


@pytest.fixture
def mock_session():
    session = MagicMock()
    with patch("meo.business_profile._AuthSession", return_value=session):
        yield session


@pytest.fixture
def client(mock_session):
    from meo.business_profile import BusinessProfileClient
    return BusinessProfileClient(MagicMock())


def test_get_local_post_returns_post_dict(client, mock_session):
    mock_session.get.return_value = _ok_resp(_POST_DATA)
    result = client.get_local_post(_POST_NAME)
    assert result["name"] == _POST_NAME
    assert result["state"] == "LIVE"


def test_get_local_post_calls_correct_url(client, mock_session):
    mock_session.get.return_value = _ok_resp(_POST_DATA)
    client.get_local_post(_POST_NAME)
    url = mock_session.get.call_args.args[0]
    assert _POST_NAME in url


def test_get_local_post_404_raises_http_error(client, mock_session):
    mock_session.get.return_value = _err_resp(404)
    with pytest.raises(requests.HTTPError):
        client.get_local_post(_POST_NAME)


def test_delete_local_post_calls_delete_on_session(client, mock_session):
    mock_session.delete.return_value = _ok_resp({})
    client.delete_local_post(_POST_NAME)
    mock_session.delete.assert_called_once()
    url = mock_session.delete.call_args.args[0]
    assert _POST_NAME in url


def test_delete_local_post_raises_on_error(client, mock_session):
    mock_session.delete.return_value = _err_resp(404)
    with pytest.raises(requests.HTTPError):
        client.delete_local_post(_POST_NAME)


def test_delete_local_post_returns_none_on_success(client, mock_session):
    mock_session.delete.return_value = _ok_resp({})
    result = client.delete_local_post(_POST_NAME)
    assert result is None

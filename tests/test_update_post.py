"""Tests for meo-update-post — fully mocked, no Google credentials needed."""

from unittest.mock import MagicMock, patch
import pytest
import requests

from meo.tools.update_post import (
    _validate_post_name,
    _validate_cta_action,
    _parse_update_time,
    _format_update_preview,
    _format_result,
    run_update_post,
    main,
)


# ---------------------------------------------------------------------------
# Shared fixtures / constants
# ---------------------------------------------------------------------------

_POST_NAME = "accounts/1/locations/2/localPosts/42"

_UPDATED_POST = {
    "name": _POST_NAME,
    "summary": "更新後のテキストです。新メニューが登場しました！",
    "topicType": "STANDARD",
    "state": "LIVE",
    "createTime": "2026-04-01T02:00:00Z",
    "updateTime": "2026-06-01T05:30:00Z",
    "callToAction": {
        "actionType": "BOOK",
        "url": "https://example.com/booking",
    },
}


def _make_gbp(*, update_return=None, update_raises=None):
    gbp = MagicMock()
    if update_raises:
        gbp.update_local_post.side_effect = update_raises
    else:
        gbp.update_local_post.return_value = update_return if update_return is not None else _UPDATED_POST
    return gbp


def _http_error(status_code: int = 404) -> requests.HTTPError:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    return requests.HTTPError(f"{status_code} Error", response=resp)


# ---------------------------------------------------------------------------
# _validate_post_name
# ---------------------------------------------------------------------------

def test_validate_post_name_valid():
    _validate_post_name("accounts/123/locations/456/localPosts/789")


def test_validate_post_name_valid_long_ids():
    _validate_post_name("accounts/999999999/locations/888888888/localPosts/AbCdEfGhIj")


def test_validate_post_name_missing_segment():
    with pytest.raises(ValueError, match="localPosts"):
        _validate_post_name("accounts/123/locations/456")


def test_validate_post_name_wrong_resource_type():
    with pytest.raises(ValueError, match="localPosts"):
        _validate_post_name("accounts/123/locations/456/reviews/789")


def test_validate_post_name_empty():
    with pytest.raises(ValueError):
        _validate_post_name("")


# ---------------------------------------------------------------------------
# _validate_cta_action
# ---------------------------------------------------------------------------

def test_validate_cta_action_valid_all():
    for action in ["BOOK", "ORDER", "SHOP", "LEARN_MORE", "SIGN_UP", "GET_OFFER", "CALL"]:
        _validate_cta_action(action)  # must not raise


def test_validate_cta_action_case_insensitive():
    _validate_cta_action("book")   # lower-case should be accepted
    _validate_cta_action("Book")   # mixed-case should be accepted


def test_validate_cta_action_invalid():
    with pytest.raises(ValueError, match="Invalid CTA action"):
        _validate_cta_action("UNKNOWN_ACTION")


def test_validate_cta_action_empty():
    with pytest.raises(ValueError):
        _validate_cta_action("")


# ---------------------------------------------------------------------------
# _parse_update_time
# ---------------------------------------------------------------------------

def test_parse_update_time_utc_z():
    result = _parse_update_time("2026-06-01T05:30:00Z")
    assert "2026-06-01" in result
    assert "JST" in result


def test_parse_update_time_with_offset():
    result = _parse_update_time("2026-06-01T14:30:00+09:00")
    assert "2026-06-01" in result


def test_parse_update_time_invalid():
    result = _parse_update_time("not-a-date")
    assert result == "not-a-date"


def test_parse_update_time_empty():
    result = _parse_update_time("")
    assert result == ""


# ---------------------------------------------------------------------------
# _format_update_preview
# ---------------------------------------------------------------------------

def test_format_update_preview_summary_only():
    out = _format_update_preview(_POST_NAME, "新しいテキスト", None, None)
    assert _POST_NAME in out
    assert "新しいテキスト" in out
    assert "CTA" not in out
    assert "URL" not in out


def test_format_update_preview_cta_only():
    out = _format_update_preview(_POST_NAME, None, "BOOK", "https://example.com")
    assert _POST_NAME in out
    assert "BOOK" in out
    assert "https://example.com" in out


def test_format_update_preview_all_fields():
    out = _format_update_preview(_POST_NAME, "テキスト", "ORDER", "https://example.com/order")
    assert "テキスト" in out
    assert "ORDER" in out
    assert "https://example.com/order" in out


def test_format_update_preview_long_summary_truncated():
    long_text = "あ" * 200
    out = _format_update_preview(_POST_NAME, long_text, None, None)
    assert "…" in out


def test_format_update_preview_summary_exactly_120_no_ellipsis():
    text = "あ" * 120
    out = _format_update_preview(_POST_NAME, text, None, None)
    assert "…" not in out


# ---------------------------------------------------------------------------
# _format_result
# ---------------------------------------------------------------------------

def test_format_result_full_post():
    out = _format_result(_UPDATED_POST)
    assert _POST_NAME in out
    assert "LIVE" in out
    assert "STANDARD" in out
    assert "JST" in out
    assert "更新後のテキスト" in out
    assert "BOOK" in out
    assert "https://example.com/booking" in out


def test_format_result_missing_fields():
    out = _format_result({})
    assert "?" in out


def test_format_result_no_cta():
    post = {**_UPDATED_POST}
    post.pop("callToAction", None)
    out = _format_result(post)
    assert "CTA" not in out


def test_format_result_long_summary_truncated():
    post = {**_UPDATED_POST, "summary": "あ" * 200}
    out = _format_result(post)
    assert "…" in out


# ---------------------------------------------------------------------------
# run_update_post
# ---------------------------------------------------------------------------

def test_run_update_post_summary_dry_run():
    gbp = _make_gbp()
    result = run_update_post(_POST_NAME, gbp, summary="新テキスト", dry_run=True)
    assert result["status"] == "dry_run"
    assert "summary" in result["fields_updated"]
    gbp.update_local_post.assert_not_called()


def test_run_update_post_cta_dry_run():
    gbp = _make_gbp()
    result = run_update_post(_POST_NAME, gbp, cta_url="https://example.com", dry_run=True)
    assert result["status"] == "dry_run"
    assert "callToAction" in result["fields_updated"]
    gbp.update_local_post.assert_not_called()


def test_run_update_post_both_fields_dry_run():
    gbp = _make_gbp()
    result = run_update_post(
        _POST_NAME, gbp,
        summary="テキスト",
        cta_action="BOOK",
        cta_url="https://example.com",
        dry_run=True,
    )
    assert result["status"] == "dry_run"
    assert "summary" in result["fields_updated"]
    assert "callToAction" in result["fields_updated"]


def test_run_update_post_live_summary():
    gbp = _make_gbp()
    result = run_update_post(_POST_NAME, gbp, summary="新しいテキスト")
    assert result["status"] == "updated"
    assert "summary" in result["fields_updated"]
    assert result["post"] == _UPDATED_POST
    gbp.update_local_post.assert_called_once_with(
        _POST_NAME, summary="新しいテキスト", cta_action=None, cta_url=None
    )


def test_run_update_post_live_cta():
    gbp = _make_gbp()
    result = run_update_post(_POST_NAME, gbp, cta_action="BOOK", cta_url="https://x.com")
    assert result["status"] == "updated"
    assert "callToAction" in result["fields_updated"]
    gbp.update_local_post.assert_called_once_with(
        _POST_NAME, summary=None, cta_action="BOOK", cta_url="https://x.com"
    )


def test_run_update_post_invalid_name_raises():
    gbp = _make_gbp()
    with pytest.raises(ValueError, match="localPosts"):
        run_update_post("accounts/1/locations/2", gbp, summary="テキスト")


def test_run_update_post_no_fields_raises():
    gbp = _make_gbp()
    with pytest.raises(ValueError, match="Nothing to update"):
        run_update_post(_POST_NAME, gbp)


def test_run_update_post_invalid_cta_action_raises():
    gbp = _make_gbp()
    with pytest.raises(ValueError, match="Invalid CTA action"):
        run_update_post(_POST_NAME, gbp, cta_action="INVALID", cta_url="https://x.com")


def test_run_update_post_api_error_propagates():
    gbp = _make_gbp(update_raises=_http_error(403))
    with pytest.raises(requests.HTTPError):
        run_update_post(_POST_NAME, gbp, summary="テキスト")


def test_run_update_post_404_propagates():
    gbp = _make_gbp(update_raises=_http_error(404))
    with pytest.raises(requests.HTTPError):
        run_update_post(_POST_NAME, gbp, summary="テキスト")


# ---------------------------------------------------------------------------
# BusinessProfileClient.update_local_post (via mock session)
# ---------------------------------------------------------------------------

def test_business_profile_update_local_post_summary():
    from unittest.mock import MagicMock
    from meo.business_profile import BusinessProfileClient
    from google.oauth2.credentials import Credentials

    creds = MagicMock(spec=Credentials)
    creds.valid = True
    creds.token = "fake-token"

    client = BusinessProfileClient(creds)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _UPDATED_POST

    with patch.object(client._session, "patch", return_value=mock_resp) as mock_patch:
        result = client.update_local_post(_POST_NAME, summary="新テキスト")

    assert result == _UPDATED_POST
    call_kwargs = mock_patch.call_args
    assert "updateMask=summary" in call_kwargs[1]["params"]["updateMask"] or \
           call_kwargs[1]["params"]["updateMask"] == "summary"
    assert call_kwargs[1]["json"]["summary"] == "新テキスト"


def test_business_profile_update_local_post_cta():
    from meo.business_profile import BusinessProfileClient
    from google.oauth2.credentials import Credentials

    creds = MagicMock(spec=Credentials)
    creds.valid = True
    creds.token = "fake-token"

    client = BusinessProfileClient(creds)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _UPDATED_POST

    with patch.object(client._session, "patch", return_value=mock_resp) as mock_patch:
        result = client.update_local_post(
            _POST_NAME, cta_action="BOOK", cta_url="https://example.com/booking"
        )

    assert result == _UPDATED_POST
    call_kwargs = mock_patch.call_args
    assert "callToAction" in call_kwargs[1]["params"]["updateMask"]
    assert call_kwargs[1]["json"]["callToAction"]["actionType"] == "BOOK"
    assert call_kwargs[1]["json"]["callToAction"]["url"] == "https://example.com/booking"


def test_business_profile_update_local_post_no_fields_raises():
    from meo.business_profile import BusinessProfileClient
    from google.oauth2.credentials import Credentials

    creds = MagicMock(spec=Credentials)
    creds.valid = True
    creds.token = "fake-token"

    client = BusinessProfileClient(creds)
    with pytest.raises(ValueError, match="At least one field"):
        client.update_local_post(_POST_NAME)


def test_business_profile_update_local_post_http_error():
    from meo.business_profile import BusinessProfileClient
    from google.oauth2.credentials import Credentials

    creds = MagicMock(spec=Credentials)
    creds.valid = True
    creds.token = "fake-token"

    client = BusinessProfileClient(creds)
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 403
    mock_resp.raise_for_status.side_effect = requests.HTTPError("403 Forbidden", response=mock_resp)
    mock_resp.json.return_value = {"error": {"message": "Permission denied"}}

    with patch.object(client._session, "patch", return_value=mock_resp):
        with pytest.raises(requests.HTTPError):
            client.update_local_post(_POST_NAME, summary="テキスト")


# ---------------------------------------------------------------------------
# _AuthSession.patch
# ---------------------------------------------------------------------------

def test_auth_session_patch_injects_bearer():
    from meo.business_profile import _AuthSession
    from google.oauth2.credentials import Credentials

    creds = MagicMock(spec=Credentials)
    creds.valid = True
    creds.token = "my-token"

    session = _AuthSession(creds)
    mock_resp = MagicMock()
    with patch.object(session._session, "patch", return_value=mock_resp) as mock_patch:
        session.patch("https://example.com/v4/some/resource", json={"key": "val"})

    _, kwargs = mock_patch.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer my-token"
    assert kwargs["json"] == {"key": "val"}


# ---------------------------------------------------------------------------
# main() CLI
# ---------------------------------------------------------------------------

def _run_main(argv):
    with patch("sys.argv", ["meo-update-post"] + argv):
        try:
            main()
        except SystemExit as exc:
            return exc.code
    return 0


def test_main_no_args_exits_1():
    code = _run_main([])
    assert code == 2  # argparse exits 2 on missing required args


def test_main_missing_post_name_exits_2():
    code = _run_main(["--summary", "テキスト"])
    assert code == 2


def test_main_no_fields_exits_1():
    code = _run_main(["--post-name", _POST_NAME])
    assert code == 1


def test_main_invalid_post_name_exits_1():
    code = _run_main(["--post-name", "accounts/1/locations/2", "--summary", "テキスト"])
    assert code == 1


def test_main_invalid_cta_action_exits_1():
    code = _run_main(["--post-name", _POST_NAME, "--cta-action", "UNKNOWN", "--cta-url", "https://x.com"])
    assert code == 1


def test_main_dry_run_summary(capsys):
    code = _run_main(["--post-name", _POST_NAME, "--summary", "新テキスト", "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0
    assert "DRY RUN" in out
    assert "新テキスト" in out


def test_main_dry_run_cta(capsys):
    code = _run_main(["--post-name", _POST_NAME, "--cta-url", "https://x.com", "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0
    assert "DRY RUN" in out
    assert "https://x.com" in out


def test_main_dry_run_cta_action(capsys):
    code = _run_main(
        ["--post-name", _POST_NAME, "--cta-action", "BOOK", "--cta-url", "https://x.com", "--dry-run"]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "BOOK" in out


def test_main_auth_failure_exits_1():
    with patch("meo.tools.update_post.get_credentials", side_effect=EnvironmentError("no creds")):
        code = _run_main(["--post-name", _POST_NAME, "--summary", "テキスト"])
    assert code == 1


def test_main_live_success(capsys):
    gbp = _make_gbp()
    with patch("meo.tools.update_post.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.update_post.BusinessProfileClient", return_value=gbp):
        code = _run_main(["--post-name", _POST_NAME, "--summary", "新しいテキスト"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Updated post" in out


def test_main_live_api_error_exits_1():
    gbp = _make_gbp(update_raises=_http_error(403))
    with patch("meo.tools.update_post.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.update_post.BusinessProfileClient", return_value=gbp):
        code = _run_main(["--post-name", _POST_NAME, "--summary", "テキスト"])
    assert code == 1


def test_main_live_all_fields(capsys):
    gbp = _make_gbp()
    with patch("meo.tools.update_post.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.update_post.BusinessProfileClient", return_value=gbp):
        code = _run_main([
            "--post-name", _POST_NAME,
            "--summary", "更新テキスト",
            "--cta-action", "BOOK",
            "--cta-url", "https://example.com/booking",
        ])
    out = capsys.readouterr().out
    assert code == 0
    assert "Updated post" in out

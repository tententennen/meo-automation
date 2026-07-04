"""Tests for BusinessProfileClient — _AuthSession is mocked to avoid real HTTP calls."""

from unittest.mock import MagicMock, patch
import pytest
import requests

from meo.business_profile import BusinessProfileClient, _AuthSession, _raise_for_status


_LOC = "accounts/1/locations/42"


def _ok(json_body: dict):
    """Build a mock requests.Response that looks like a successful API call."""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = json_body
    return resp


@pytest.fixture
def mock_session():
    """Patch _AuthSession so BusinessProfileClient never opens a real socket."""
    session = MagicMock()
    with patch("meo.business_profile._AuthSession", return_value=session):
        yield session


@pytest.fixture
def client(mock_session):
    return BusinessProfileClient(MagicMock())


# ---------------------------------------------------------------------------
# create_local_post
# ---------------------------------------------------------------------------

def test_create_local_post_returns_resource(client, mock_session):
    mock_session.post.return_value = _ok({"name": f"{_LOC}/localPosts/1"})
    result = client.create_local_post(_LOC, "春のキャンペーン開催中！")
    assert result["name"].endswith("localPosts/1")


def test_create_local_post_sends_correct_body_fields(client, mock_session):
    mock_session.post.return_value = _ok({"name": f"{_LOC}/localPosts/2"})
    client.create_local_post(_LOC, "テスト投稿")
    body = mock_session.post.call_args.kwargs["json"]
    assert body["summary"] == "テスト投稿"
    assert body["topicType"] == "STANDARD"
    assert body["languageCode"] == "ja"


def test_create_local_post_attaches_media_when_url_given(client, mock_session):
    mock_session.post.return_value = _ok({"name": f"{_LOC}/localPosts/3"})
    client.create_local_post(_LOC, "写真付き投稿", media_url="https://example.com/img.jpg")
    body = mock_session.post.call_args.kwargs["json"]
    assert body["media"] == [{"mediaFormat": "PHOTO", "sourceUrl": "https://example.com/img.jpg"}]


def test_create_local_post_omits_media_field_when_no_url(client, mock_session):
    mock_session.post.return_value = _ok({"name": f"{_LOC}/localPosts/4"})
    client.create_local_post(_LOC, "写真なし投稿", media_url=None)
    body = mock_session.post.call_args.kwargs["json"]
    assert "media" not in body


def test_create_local_post_includes_call_to_action_when_given(client, mock_session):
    mock_session.post.return_value = _ok({"name": f"{_LOC}/localPosts/5"})
    cta = {"actionType": "BOOK", "url": "https://example.com/book"}
    client.create_local_post(_LOC, "予約はこちら", call_to_action=cta)
    body = mock_session.post.call_args.kwargs["json"]
    assert body["callToAction"] == cta


def test_create_local_post_omits_call_to_action_when_none(client, mock_session):
    mock_session.post.return_value = _ok({"name": f"{_LOC}/localPosts/6"})
    client.create_local_post(_LOC, "CTAなし投稿", call_to_action=None)
    body = mock_session.post.call_args.kwargs["json"]
    assert "callToAction" not in body


# ---------------------------------------------------------------------------
# upload_media_bytes
# ---------------------------------------------------------------------------

def test_upload_media_returns_google_url(client, mock_session):
    mock_session.post.return_value = _ok({"googleUrl": "https://lh3.example.com/hosted/img"})
    url = client.upload_media_bytes(_LOC, b"\xff\xd8\xff")
    assert url == "https://lh3.example.com/hosted/img"


def test_upload_media_falls_back_to_source_url(client, mock_session):
    mock_session.post.return_value = _ok({"sourceUrl": "https://source.example.com/img"})
    url = client.upload_media_bytes(_LOC, b"\xff\xd8\xff")
    assert url == "https://source.example.com/img"


def test_upload_media_raises_when_response_has_no_url(client, mock_session):
    mock_session.post.return_value = _ok({"name": "media/xyz"})
    with pytest.raises(RuntimeError, match="returned no URL"):
        client.upload_media_bytes(_LOC, b"\xff\xd8\xff")


def test_upload_media_sends_multipart_content_type(client, mock_session):
    mock_session.post.return_value = _ok({"googleUrl": "https://lh3.example.com/x"})
    client.upload_media_bytes(_LOC, b"\xff\xd8\xff", mime_type="image/png")
    call_headers = mock_session.post.call_args.kwargs["headers"]
    assert "multipart/related" in call_headers["Content-Type"]


# ---------------------------------------------------------------------------
# list_reviews
# ---------------------------------------------------------------------------

def test_list_reviews_returns_all_reviews(client, mock_session):
    mock_session.get.return_value = _ok({
        "reviews": [
            {"reviewId": "r1", "starRating": "FIVE"},
            {"reviewId": "r2", "starRating": "THREE"},
        ]
    })
    reviews = client.list_reviews(_LOC)
    assert len(reviews) == 2
    assert {r["reviewId"] for r in reviews} == {"r1", "r2"}


def test_list_reviews_returns_empty_list_when_none(client, mock_session):
    mock_session.get.return_value = _ok({})
    assert client.list_reviews(_LOC) == []


def test_list_reviews_handles_pagination(client, mock_session):
    mock_session.get.side_effect = [
        _ok({"reviews": [{"reviewId": "r1"}], "nextPageToken": "tok1"}),
        _ok({"reviews": [{"reviewId": "r2"}]}),
    ]
    reviews = client.list_reviews(_LOC)
    assert len(reviews) == 2
    assert {r["reviewId"] for r in reviews} == {"r1", "r2"}
    assert mock_session.get.call_count == 2


# ---------------------------------------------------------------------------
# reply_to_review
# ---------------------------------------------------------------------------

def test_reply_to_review_sends_comment_body(client, mock_session):
    mock_session.put.return_value = _ok({"comment": "返信内容"})
    result = client.reply_to_review(_LOC, "rev_abc", "ありがとうございます！")
    call_body = mock_session.put.call_args.kwargs["json"]
    assert call_body["comment"] == "ありがとうございます！"
    assert result["comment"] == "返信内容"


# ---------------------------------------------------------------------------
# _AuthSession internals
# ---------------------------------------------------------------------------

def test_auth_session_injects_bearer_token():
    creds = MagicMock()
    creds.valid = True
    creds.token = "test_access_token"
    session = _AuthSession(creds)
    headers = session._auth_headers()
    assert headers["Authorization"] == "Bearer test_access_token"


def test_auth_session_merges_caller_headers():
    creds = MagicMock()
    creds.valid = True
    creds.token = "tok_xyz"
    session = _AuthSession(creds)
    headers = session._auth_headers({"Content-Type": "multipart/related"})
    assert headers["Authorization"] == "Bearer tok_xyz"
    assert headers["Content-Type"] == "multipart/related"


# ---------------------------------------------------------------------------
# Timeout and retry configuration
# ---------------------------------------------------------------------------

def test_auth_session_get_passes_default_timeout():
    """GET requests from _AuthSession must carry the (connect, read) timeout."""
    from unittest.mock import patch as _patch
    creds = MagicMock()
    creds.valid = True
    creds.token = "tok"
    auth = _AuthSession(creds)
    mock_resp = _ok({})
    with _patch.object(auth._session, "get", return_value=mock_resp) as mock_get:
        auth.get("https://example.com/api")
    call_kwargs = mock_get.call_args.kwargs
    assert "timeout" in call_kwargs
    connect_t, read_t = call_kwargs["timeout"]
    assert connect_t > 0 and read_t > 0


def test_auth_session_post_passes_default_timeout():
    """POST requests from _AuthSession must carry the (connect, read) timeout."""
    from unittest.mock import patch as _patch
    creds = MagicMock()
    creds.valid = True
    creds.token = "tok"
    auth = _AuthSession(creds)
    mock_resp = _ok({})
    with _patch.object(auth._session, "post", return_value=mock_resp) as mock_post:
        auth.post("https://example.com/api", json={"key": "value"})
    call_kwargs = mock_post.call_args.kwargs
    assert "timeout" in call_kwargs
    connect_t, read_t = call_kwargs["timeout"]
    assert connect_t > 0 and read_t > 0


def test_auth_session_put_passes_default_timeout():
    """PUT requests from _AuthSession must carry the (connect, read) timeout."""
    from unittest.mock import patch as _patch
    creds = MagicMock()
    creds.valid = True
    creds.token = "tok"
    auth = _AuthSession(creds)
    mock_resp = _ok({})
    with _patch.object(auth._session, "put", return_value=mock_resp) as mock_put:
        auth.put("https://example.com/api", json={"key": "value"})
    call_kwargs = mock_put.call_args.kwargs
    assert "timeout" in call_kwargs
    connect_t, read_t = call_kwargs["timeout"]
    assert connect_t > 0 and read_t > 0


def test_retry_config_includes_put():
    """PUT must be in the allowed_methods of the retry adapter so reply_to_review retries."""
    from requests.adapters import HTTPAdapter
    creds = MagicMock()
    creds.valid = True
    creds.token = "tok"
    session = _AuthSession(creds)
    # Inspect the HTTPAdapter mounted on 'https://'
    adapter = session._session.get_adapter("https://example.com")
    assert isinstance(adapter, HTTPAdapter)
    # urllib3 Retry stores allowed_methods as a frozenset
    allowed = adapter.max_retries.allowed_methods
    assert "PUT" in allowed
    assert "GET" in allowed
    assert "POST" not in allowed  # POST is not idempotent — must never be auto-retried


# ---------------------------------------------------------------------------
# _refresh_if_needed — credential expiry handling
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# _raise_for_status
# ---------------------------------------------------------------------------

def _error_resp(status_code: int, json_body: dict | None = None, text: str = "") -> MagicMock:
    """Build a mock response that simulates a failed API call."""
    resp = MagicMock()
    resp.ok = False
    resp.status_code = status_code
    resp.text = text
    if json_body is not None:
        resp.json.return_value = json_body
    else:
        resp.json.side_effect = ValueError("not json")
    resp.raise_for_status.side_effect = requests.HTTPError(
        f"{status_code} Client Error", response=resp
    )
    return resp


def test_raise_for_status_is_noop_on_success():
    resp = MagicMock()
    resp.ok = True
    _raise_for_status(resp)  # must not raise


def test_raise_for_status_includes_api_error_message():
    resp = _error_resp(
        400,
        json_body={"error": {"code": 400, "message": "Invalid location ID", "status": "INVALID_ARGUMENT"}},
    )
    with pytest.raises(requests.HTTPError, match="Invalid location ID"):
        _raise_for_status(resp)


def test_raise_for_status_403_appends_api_access_hint():
    resp = _error_resp(
        403,
        json_body={"error": {"code": 403, "message": "PERMISSION_DENIED", "status": "PERMISSION_DENIED"}},
    )
    with pytest.raises(requests.HTTPError, match="prereqs"):
        _raise_for_status(resp)


def test_raise_for_status_non_json_uses_text_excerpt():
    resp = _error_resp(500, json_body=None, text="Internal Server Error details here")
    with pytest.raises(requests.HTTPError, match="Internal Server Error"):
        _raise_for_status(resp)


def test_raise_for_status_non_403_does_not_add_hint():
    resp = _error_resp(
        404,
        json_body={"error": {"code": 404, "message": "Not found", "status": "NOT_FOUND"}},
    )
    with pytest.raises(requests.HTTPError) as exc_info:
        _raise_for_status(resp)
    assert "prereqs" not in str(exc_info.value)


# ---------------------------------------------------------------------------

def test_refresh_if_needed_does_nothing_when_creds_valid():
    """When credentials are still valid, no refresh call is made."""
    creds = MagicMock()
    creds.valid = True
    creds.token = "tok"
    session = _AuthSession(creds)
    session._refresh_if_needed()
    creds.refresh.assert_not_called()


def test_refresh_if_needed_refreshes_when_creds_invalid():
    """When credentials have expired, refresh() is called with a Request object."""
    creds = MagicMock()
    creds.valid = False
    creds.token = "tok"
    session = _AuthSession(creds)
    with patch("google.auth.transport.requests.Request") as mock_request_cls:
        mock_req = MagicMock()
        mock_request_cls.return_value = mock_req
        session._refresh_if_needed()
    creds.refresh.assert_called_once_with(mock_req)

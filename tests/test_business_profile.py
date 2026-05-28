"""Tests for meo.business_profile — all HTTP calls are mocked."""

from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch

from meo.business_profile import BusinessProfileClient, _AuthSession


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_creds(token: str = "tok") -> MagicMock:
    creds = MagicMock()
    creds.valid = True
    creds.token = token
    return creds


def _make_client(mock_session: MagicMock) -> BusinessProfileClient:
    """Build a BusinessProfileClient whose _AuthSession uses mock_session."""
    creds = _make_creds()
    client = BusinessProfileClient.__new__(BusinessProfileClient)
    client._creds = creds
    auth_session = _AuthSession.__new__(_AuthSession)
    auth_session._creds = creds
    auth_session._session = mock_session
    client._session = auth_session
    return client


def _mock_response(body: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body
    resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# create_local_post
# ---------------------------------------------------------------------------

class TestCreateLocalPost:
    def test_posts_json_body(self):
        session = MagicMock()
        session.post.return_value = _mock_response({"name": "accounts/1/locations/2/localPosts/3"})
        client = _make_client(session)

        result = client.create_local_post("accounts/1/locations/2", "テスト投稿")

        assert result["name"] == "accounts/1/locations/2/localPosts/3"
        call_kwargs = session.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert body["summary"] == "テスト投稿"
        assert body["topicType"] == "STANDARD"
        assert body["languageCode"] == "ja"

    def test_attaches_media_url_when_provided(self):
        session = MagicMock()
        session.post.return_value = _mock_response({"name": "posts/x"})
        client = _make_client(session)

        client.create_local_post("accounts/1/locations/2", "本文", media_url="https://img.example.com/1.jpg")

        body = session.post.call_args.kwargs.get("json") or session.post.call_args[1]["json"]
        assert body["media"] == [{"mediaFormat": "PHOTO", "sourceUrl": "https://img.example.com/1.jpg"}]

    def test_no_media_key_when_url_omitted(self):
        session = MagicMock()
        session.post.return_value = _mock_response({"name": "posts/x"})
        client = _make_client(session)

        client.create_local_post("accounts/1/locations/2", "本文")

        body = session.post.call_args.kwargs.get("json") or session.post.call_args[1]["json"]
        assert "media" not in body

    def test_includes_call_to_action(self):
        session = MagicMock()
        session.post.return_value = _mock_response({"name": "posts/x"})
        client = _make_client(session)

        cta = {"actionType": "BOOK", "url": "https://example.com/book"}
        client.create_local_post("accounts/1/locations/2", "本文", call_to_action=cta)

        body = session.post.call_args.kwargs.get("json") or session.post.call_args[1]["json"]
        assert body["callToAction"] == cta

    def test_raises_on_http_error(self):
        session = MagicMock()
        resp = MagicMock()
        resp.raise_for_status.side_effect = Exception("403 Forbidden")
        session.post.return_value = resp
        client = _make_client(session)

        with pytest.raises(Exception, match="403 Forbidden"):
            client.create_local_post("accounts/1/locations/2", "本文")


# ---------------------------------------------------------------------------
# upload_media_bytes
# ---------------------------------------------------------------------------

class TestUploadMediaBytes:
    def test_returns_google_url(self):
        session = MagicMock()
        session.post.return_value = _mock_response({"googleUrl": "https://lh3.google.com/u/abc"})
        client = _make_client(session)

        url = client.upload_media_bytes("accounts/1/locations/2", b"\xff\xd8\xff\xe0")

        assert url == "https://lh3.google.com/u/abc"

    def test_falls_back_to_source_url(self):
        session = MagicMock()
        session.post.return_value = _mock_response({"sourceUrl": "https://cdn.example.com/img.jpg"})
        client = _make_client(session)

        url = client.upload_media_bytes("accounts/1/locations/2", b"\x89PNG")

        assert url == "https://cdn.example.com/img.jpg"

    def test_raises_when_no_url_in_response(self):
        session = MagicMock()
        session.post.return_value = _mock_response({"name": "media/123"})
        client = _make_client(session)

        with pytest.raises(RuntimeError, match="no URL"):
            client.upload_media_bytes("accounts/1/locations/2", b"data")

    def test_sends_multipart_content_type(self):
        session = MagicMock()
        session.post.return_value = _mock_response({"googleUrl": "https://lh3.google.com/u/abc"})
        client = _make_client(session)

        client.upload_media_bytes("accounts/1/locations/2", b"data", mime_type="image/png")

        call_kwargs = session.post.call_args.kwargs
        headers = call_kwargs.get("headers", {})
        assert "multipart/related" in headers.get("Content-Type", "")


# ---------------------------------------------------------------------------
# list_reviews
# ---------------------------------------------------------------------------

class TestListReviews:
    def test_returns_reviews(self):
        reviews = [{"reviewId": "r1"}, {"reviewId": "r2"}]
        session = MagicMock()
        session.get.return_value = _mock_response({"reviews": reviews})
        client = _make_client(session)

        result = client.list_reviews("accounts/1/locations/2")

        assert len(result) == 2
        assert result[0]["reviewId"] == "r1"

    def test_handles_empty_reviews(self):
        session = MagicMock()
        session.get.return_value = _mock_response({})
        client = _make_client(session)

        result = client.list_reviews("accounts/1/locations/2")

        assert result == []

    def test_follows_pagination(self):
        page1 = {"reviews": [{"reviewId": "r1"}], "nextPageToken": "tok2"}
        page2 = {"reviews": [{"reviewId": "r2"}]}
        session = MagicMock()
        session.get.side_effect = [_mock_response(page1), _mock_response(page2)]
        client = _make_client(session)

        result = client.list_reviews("accounts/1/locations/2")

        assert len(result) == 2
        assert session.get.call_count == 2
        second_call_params = session.get.call_args_list[1].kwargs.get("params", {})
        assert second_call_params.get("pageToken") == "tok2"


# ---------------------------------------------------------------------------
# reply_to_review
# ---------------------------------------------------------------------------

class TestReplyToReview:
    def test_puts_comment_body(self):
        session = MagicMock()
        session.put.return_value = _mock_response({"comment": "ありがとうございます！"})
        client = _make_client(session)

        result = client.reply_to_review("accounts/1/locations/2", "r1", "ありがとうございます！")

        assert result["comment"] == "ありがとうございます！"
        body = session.put.call_args.kwargs.get("json") or session.put.call_args[1]["json"]
        assert body == {"comment": "ありがとうございます！"}

    def test_url_includes_review_id(self):
        session = MagicMock()
        session.put.return_value = _mock_response({})
        client = _make_client(session)

        client.reply_to_review("accounts/1/locations/2", "myreview99", "返信テキスト")

        call_url = session.put.call_args.args[0] if session.put.call_args.args else session.put.call_args[0][0]
        assert "myreview99" in call_url


# ---------------------------------------------------------------------------
# _AuthSession header merging
# ---------------------------------------------------------------------------

class TestAuthSessionHeaders:
    def test_injects_bearer_token(self):
        creds = _make_creds("mytoken123")
        session_inner = MagicMock()
        session_inner.get.return_value = _mock_response({})
        auth_session = _AuthSession.__new__(_AuthSession)
        auth_session._creds = creds
        auth_session._session = session_inner

        auth_session.get("https://example.com/api")

        headers = session_inner.get.call_args.kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer mytoken123"

    def test_merges_caller_headers(self):
        creds = _make_creds("tok")
        session_inner = MagicMock()
        session_inner.post.return_value = _mock_response({})
        auth_session = _AuthSession.__new__(_AuthSession)
        auth_session._creds = creds
        auth_session._session = session_inner

        auth_session.post("https://example.com/api", headers={"X-Custom": "yes"})

        headers = session_inner.post.call_args.kwargs.get("headers", {})
        assert "Authorization" in headers
        assert headers["X-Custom"] == "yes"

    def test_refreshes_when_creds_invalid(self):
        creds = MagicMock()
        creds.valid = False
        creds.token = "freshtoken"

        session_inner = MagicMock()
        session_inner.get.return_value = _mock_response({})
        auth_session = _AuthSession.__new__(_AuthSession)
        auth_session._creds = creds
        auth_session._session = session_inner

        # Request is lazily imported inside _refresh_if_needed
        with patch("google.auth.transport.requests.Request"):
            auth_session.get("https://example.com/api")

        creds.refresh.assert_called_once()

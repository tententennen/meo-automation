"""Tests for AI content generation — mocks the LLM so no API key is needed."""

from unittest.mock import patch, MagicMock
import pytest

from meo import content, config as cfg


_STORE = {
    "key": "the_body_kyoto",
    "name": "THE BODY 京都店",
    "industry": "beauty_salon",
}

_REVIEW = {
    "reviewId": "abc123",
    "name": "accounts/1/locations/2/reviews/abc123",
    "reviewer": {"displayName": "田中太郎"},
    "starRating": "FIVE",
    "comment": "スタッフが優しく、とても良い体験でした。",
}


def _mock_llm(text: str):
    """Return a patcher that makes _call_llm return `text`."""
    return patch("meo.content._call_llm", return_value=text)


def test_generate_post_returns_string():
    with _mock_llm("新しいコースが始まりました！ぜひお越しください。"):
        result = content.generate_post(_STORE)
    assert isinstance(result, str)
    assert len(result) > 0


def test_generate_post_truncates_to_max_chars():
    long_text = "あ" * 9999
    with _mock_llm(long_text):
        result = content.generate_post(_STORE)
    max_chars = cfg.content()["defaults"]["max_post_chars"]
    assert len(result) <= max_chars


def test_generate_reply_returns_string():
    with _mock_llm("田中様、ありがとうございます！またのご来店をお待ちしております。"):
        result = content.generate_reply(_REVIEW, _STORE)
    assert isinstance(result, str)
    assert len(result) > 0


def test_generate_reply_truncates_to_max_chars():
    long_text = "あ" * 99999
    with _mock_llm(long_text):
        result = content.generate_reply(_REVIEW, _STORE)
    max_chars = cfg.content()["defaults"]["max_reply_chars"]
    assert len(result) <= max_chars


def test_call_llm_raises_on_unknown_provider():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        content._call_llm("test", {"provider": "fake_provider"})

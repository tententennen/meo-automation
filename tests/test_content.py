"""Tests for AI content generation — mocks the LLM so no API key is needed."""

from datetime import datetime
from unittest.mock import patch, MagicMock
import pytest
from zoneinfo import ZoneInfo

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


def test_call_llm_openai_provider():
    """OpenAI branch routes correctly even without the package installed."""
    fake_response = MagicMock()
    fake_response.choices = [MagicMock()]
    fake_response.choices[0].message.content = "OpenAI生成テキスト"

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response

    import types
    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = MagicMock(return_value=fake_client)
    fake_openai.RateLimitError = Exception
    fake_openai.APIError = Exception

    import sys
    sys.modules["openai"] = fake_openai
    import os
    os.environ.setdefault("OPENAI_API_KEY", "test-key")

    try:
        result = content._call_llm("テスト", {"provider": "openai", "model_id": "gpt-4o-mini"})
        assert result == "OpenAI生成テキスト"
    finally:
        sys.modules.pop("openai", None)


def test_generate_post_with_forced_theme_includes_it_in_prompt():
    """When forced_theme is given the LLM prompt should name it explicitly."""
    theme = "季節のお手入れ情報"
    with patch("meo.content._call_llm", return_value="テスト投稿") as mock_llm:
        content.generate_post(_STORE, forced_theme=theme)
    user_prompt = mock_llm.call_args.args[0]
    assert theme in user_prompt
    # Explicit-theme path must NOT list multiple theme candidates
    assert "テーマ候補" not in user_prompt


def test_generate_post_without_forced_theme_lists_all_themes():
    """When forced_theme is omitted all configured themes appear in the prompt."""
    from meo import config as cfg
    conf = cfg.content()
    industry = _STORE.get("industry", "beauty_salon")
    expected_themes = conf["industry_tones"][industry]["themes"]

    with patch("meo.content._call_llm", return_value="テスト投稿") as mock_llm:
        content.generate_post(_STORE)
    user_prompt = mock_llm.call_args.args[0]
    assert "テーマ候補" in user_prompt
    for t in expected_themes:
        assert t in user_prompt


# ---------------------------------------------------------------------------
# _season() tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("month,expected", [
    (3, "春"), (4, "春"), (5, "春"),
    (6, "夏"), (7, "夏"), (8, "夏"),
    (9, "秋"), (10, "秋"), (11, "秋"),
    (12, "冬"), (1, "冬"), (2, "冬"),
])
def test_season_mapping(month, expected):
    assert content._season(month) == expected


# ---------------------------------------------------------------------------
# Date/season context injection tests
# ---------------------------------------------------------------------------

def _frozen_jst(year: int, month: int, day: int):
    """Return a patcher that freezes _jst_date_context() to a known string."""
    fixed = f"{year}年{month}月{day}日（{content._season(month)}）"
    return patch("meo.content._jst_date_context", return_value=fixed), fixed


def test_generate_post_includes_date_context():
    """generate_post() must inject the current date/season into the user prompt."""
    patcher, fixed_ctx = _frozen_jst(2026, 5, 31)
    with patcher, patch("meo.content._call_llm", return_value="テスト投稿") as mock_llm:
        content.generate_post(_STORE)
    user_prompt = mock_llm.call_args.args[0]
    assert fixed_ctx in user_prompt


def test_generate_post_forced_theme_also_includes_date_context():
    """Date context must appear even when a forced_theme is supplied."""
    patcher, fixed_ctx = _frozen_jst(2026, 12, 1)
    with patcher, patch("meo.content._call_llm", return_value="テスト投稿") as mock_llm:
        content.generate_post(_STORE, forced_theme="季節のお手入れ情報")
    user_prompt = mock_llm.call_args.args[0]
    assert fixed_ctx in user_prompt


def test_generate_reply_includes_date_context():
    """generate_reply() must inject the current date/season into the user prompt."""
    patcher, fixed_ctx = _frozen_jst(2026, 8, 15)
    with patcher, patch("meo.content._call_llm", return_value="ありがとうございます") as mock_llm:
        content.generate_reply(_REVIEW, _STORE)
    user_prompt = mock_llm.call_args.args[0]
    assert fixed_ctx in user_prompt


def test_jst_date_context_contains_year_and_season():
    """_jst_date_context() returns a string containing year and parenthesised season."""
    ctx = content._jst_date_context()
    assert "年" in ctx
    assert "月" in ctx
    assert "日" in ctx
    # One of the four seasons must appear in parentheses
    assert any(s in ctx for s in ("（春）", "（夏）", "（秋）", "（冬）"))

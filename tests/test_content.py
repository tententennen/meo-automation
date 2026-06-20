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


# ---------------------------------------------------------------------------
# Anthropic prompt caching
# ---------------------------------------------------------------------------

def _make_fake_anthropic(fake_client):
    """Build a minimal fake anthropic module wired to fake_client."""
    import types
    mod = types.ModuleType("anthropic")
    mod.Anthropic = MagicMock(return_value=fake_client)
    mod.RateLimitError = Exception
    mod.APIError = Exception
    return mod


def test_call_anthropic_passes_system_as_cached_block():
    """System prompt must be forwarded as a content block with cache_control.

    Anthropic's prompt caching API requires the system parameter to be a list
    of typed content blocks (not a plain string) when cache_control is used.
    Cache hits save ~90% of cached-prefix token costs across same-day runs.
    """
    import sys, os

    fake_msg = MagicMock()
    fake_msg.content = [MagicMock(text="テスト")]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_msg

    fake_anthropic = _make_fake_anthropic(fake_client)
    sys.modules["anthropic"] = fake_anthropic
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

    try:
        content._call_anthropic("prompt", {"model_id": "test"}, system="システム")
        call_kw = fake_client.messages.create.call_args.kwargs
        system_arg = call_kw["system"]
        assert isinstance(system_arg, list), "system must be a list of content blocks"
        assert len(system_arg) == 1
        block = system_arg[0]
        assert block["type"] == "text"
        assert block["text"] == "システム"
        assert block["cache_control"] == {"type": "ephemeral"}
    finally:
        sys.modules.pop("anthropic", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)


def test_call_anthropic_without_system_omits_system_key():
    """When no system prompt is provided the 'system' key must be absent entirely."""
    import sys, os

    fake_msg = MagicMock()
    fake_msg.content = [MagicMock(text="テスト")]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_msg

    fake_anthropic = _make_fake_anthropic(fake_client)
    sys.modules["anthropic"] = fake_anthropic
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

    try:
        content._call_anthropic("prompt", {"model_id": "test"})
        call_kw = fake_client.messages.create.call_args.kwargs
        assert "system" not in call_kw
    finally:
        sys.modules.pop("anthropic", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)


# ---------------------------------------------------------------------------
# Retry logic tests (_call_with_retry)
# ---------------------------------------------------------------------------

def test_call_with_retry_succeeds_immediately():
    """When the first attempt succeeds, no sleep occurs."""
    calls: list[int] = []

    def fn():
        calls.append(1)
        return "ok"

    with patch("meo.content.time.sleep") as mock_sleep:
        result = content._call_with_retry(fn, max_attempts=3)

    assert result == "ok"
    assert len(calls) == 1
    mock_sleep.assert_not_called()


def test_call_with_retry_succeeds_on_second_attempt():
    """When the first attempt raises RuntimeError, the second attempt succeeds."""
    calls: list[int] = []

    def fn():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient error")
        return "ok"

    with patch("meo.content.time.sleep"):
        result = content._call_with_retry(fn, max_attempts=3)

    assert result == "ok"
    assert len(calls) == 2


def test_call_with_retry_raises_after_all_attempts_fail():
    """After max_attempts failures the last exception is re-raised."""
    def fn():
        raise RuntimeError("persistent error")

    with patch("meo.content.time.sleep"):
        with pytest.raises(RuntimeError, match="persistent error"):
            content._call_with_retry(fn, max_attempts=3)


def test_call_with_retry_does_not_retry_environment_error():
    """EnvironmentError (missing API key) is re-raised immediately without retry."""
    calls: list[int] = []

    def fn():
        calls.append(1)
        raise EnvironmentError("no key")

    with patch("meo.content.time.sleep") as mock_sleep:
        with pytest.raises(EnvironmentError):
            content._call_with_retry(fn, max_attempts=3)

    assert len(calls) == 1
    mock_sleep.assert_not_called()


def test_call_with_retry_sleeps_between_attempts():
    """A sleep call must occur between each failed attempt."""
    calls: list[int] = []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("fail")
        return "ok"

    with patch("meo.content.time.sleep") as mock_sleep:
        content._call_with_retry(fn, max_attempts=3, base_delay=1.0)

    assert mock_sleep.call_count == 2  # slept after attempt 1 and 2


# ---------------------------------------------------------------------------
# _star_label() tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rating,expected", [
    ("ONE",   "★☆☆☆☆（1/5）"),
    ("TWO",   "★★☆☆☆（2/5）"),
    ("THREE", "★★★☆☆（3/5）"),
    ("FOUR",  "★★★★☆（4/5）"),
    ("FIVE",  "★★★★★（5/5）"),
])
def test_star_label_known_ratings(rating, expected):
    assert content._star_label(rating) == expected


def test_star_label_unknown_returns_raw():
    assert content._star_label("UNKNOWN_RATING") == "UNKNOWN_RATING"


def test_generate_reply_uses_star_label_in_prompt():
    """Star rating must appear as ★ symbols in the LLM prompt."""
    review = dict(_REVIEW, starRating="THREE")
    with patch("meo.content._call_llm", return_value="返信テキスト") as mock_llm:
        content.generate_reply(review, _STORE)
    user_prompt = mock_llm.call_args.args[0]
    assert "★★★☆☆" in user_prompt
    assert "THREE" not in user_prompt  # raw API string must not leak through


def test_generate_reply_empty_comment_shows_no_comment_label():
    """A review with an empty comment string shows 'コメントなし' in the prompt."""
    review = dict(_REVIEW, comment="")
    with patch("meo.content._call_llm", return_value="返信テキスト") as mock_llm:
        content.generate_reply(review, _STORE)
    user_prompt = mock_llm.call_args.args[0]
    assert "コメントなし" in user_prompt


def test_generate_reply_missing_comment_key_shows_no_comment_label():
    """A review dict without a 'comment' key at all shows 'コメントなし'."""
    review = {k: v for k, v in _REVIEW.items() if k != "comment"}
    with patch("meo.content._call_llm", return_value="返信テキスト") as mock_llm:
        content.generate_reply(review, _STORE)
    user_prompt = mock_llm.call_args.args[0]
    assert "コメントなし" in user_prompt


def test_generate_reply_nonempty_comment_is_passed_through():
    """When a review has a comment, the actual comment text appears in the prompt."""
    review = dict(_REVIEW, comment="とても良い体験でした。")
    with patch("meo.content._call_llm", return_value="返信テキスト") as mock_llm:
        content.generate_reply(review, _STORE)
    user_prompt = mock_llm.call_args.args[0]
    assert "とても良い体験でした。" in user_prompt
    # The レビュー内容 line must contain the real text, not the no-comment placeholder.
    for line in user_prompt.splitlines():
        if line.startswith("レビュー内容:"):
            assert "（コメントなし）" not in line
            break


def test_call_with_retry_rate_limit_uses_longer_delay():
    """Rate-limit errors must get a longer backoff than generic API errors."""
    def make_fn(error_msg):
        calls: list[int] = []
        def fn():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError(error_msg)
            return "ok"
        return fn

    rate_delays: list[float] = []
    generic_delays: list[float] = []

    with patch("meo.content.time.sleep", side_effect=lambda d: rate_delays.append(d)):
        content._call_with_retry(make_fn("rate limit reached"), max_attempts=3, base_delay=1.0)

    with patch("meo.content.time.sleep", side_effect=lambda d: generic_delays.append(d)):
        content._call_with_retry(make_fn("server error 500"), max_attempts=3, base_delay=1.0)

    assert len(rate_delays) == 1
    assert len(generic_delays) == 1
    assert rate_delays[0] > generic_delays[0]


# ---------------------------------------------------------------------------
# Banned-word detection tests
# ---------------------------------------------------------------------------

def test_check_banned_words_finds_match():
    found = content._check_banned_words("激安キャンペーン中！", ["激安", "最安値"])
    assert found == ["激安"]


def test_check_banned_words_case_insensitive():
    found = content._check_banned_words("SALE 100%保証品質", ["100%保証"])
    assert "100%保証" in found


def test_check_banned_words_returns_empty_when_no_match():
    found = content._check_banned_words("春のキャンペーン開催中です！", ["激安", "最安値"])
    assert found == []


def test_generate_post_logs_warning_when_banned_word_found(caplog):
    import logging
    with _mock_llm("激安クーポンあり！"):
        with caplog.at_level(logging.WARNING, logger="meo.content"):
            content.generate_post(_STORE)
    assert any("激安" in r.message for r in caplog.records)


def test_generate_post_no_warning_when_no_banned_word(caplog):
    import logging
    with _mock_llm("春のキャンペーンを開催中です！"):
        with caplog.at_level(logging.WARNING, logger="meo.content"):
            content.generate_post(_STORE)
    assert not any("banned word" in r.message for r in caplog.records)


def test_generate_reply_logs_warning_when_banned_word_found(caplog):
    import logging
    with _mock_llm("激安サービスをご利用ください"):
        with caplog.at_level(logging.WARNING, logger="meo.content"):
            content.generate_reply(_REVIEW, _STORE)
    assert any("激安" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Per-store max_chars override tests
# ---------------------------------------------------------------------------

def test_generate_post_respects_per_store_max_chars_override():
    """A per-store max_post_chars override must constrain the generated text.

    This verifies the fix: generate_post() must use cfg.effective_defaults(store)
    for max_post_chars, not the global defaults dict.  A store with a small override
    (200 chars) must produce a shorter result than the global default (1500 chars).
    """
    store_with_override = {**_STORE, "overrides": {"max_post_chars": 200}}
    long_text = "あ" * 9999
    with _mock_llm(long_text):
        result = content.generate_post(store_with_override)
    assert len(result) <= 200


def test_generate_reply_respects_per_store_max_chars_override():
    """A per-store max_reply_chars override must constrain the generated reply.

    This verifies the fix: generate_reply() must use cfg.effective_defaults(store)
    for max_reply_chars, not the global defaults dict.
    """
    store_with_override = {**_STORE, "overrides": {"max_reply_chars": 150}}
    long_text = "あ" * 9999
    with _mock_llm(long_text):
        result = content.generate_reply(_REVIEW, store_with_override)
    assert len(result) <= 150


# ---------------------------------------------------------------------------
# Provider exception-handler coverage
# Tests that provider-specific errors are correctly converted to RuntimeError
# (which _call_with_retry uses to detect and retry transient failures).
# ---------------------------------------------------------------------------

def _make_fake_anthropic_with_error(exc_class_name: str):
    """Build a fake anthropic module whose messages.create raises exc_class_name."""
    import sys
    import types

    class FakeRateLimitError(Exception):
        pass

    class FakeAPIError(Exception):
        pass

    exc = FakeRateLimitError if exc_class_name == "RateLimitError" else FakeAPIError

    fake_client = MagicMock()
    fake_client.messages.create.side_effect = exc("triggered in test")

    mod = types.ModuleType("anthropic")
    mod.Anthropic = MagicMock(return_value=fake_client)
    mod.RateLimitError = FakeRateLimitError
    mod.APIError = FakeAPIError
    sys.modules["anthropic"] = mod
    return mod


def _make_fake_openai_with_error(exc_class_name: str):
    """Build a fake openai module whose chat.completions.create raises exc_class_name."""
    import sys
    import types

    class FakeRateLimitError(Exception):
        pass

    class FakeAPIError(Exception):
        pass

    exc = FakeRateLimitError if exc_class_name == "RateLimitError" else FakeAPIError

    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = exc("triggered in test")

    mod = types.ModuleType("openai")
    mod.OpenAI = MagicMock(return_value=fake_client)
    mod.RateLimitError = FakeRateLimitError
    mod.APIError = FakeAPIError
    sys.modules["openai"] = mod
    return mod


def test_call_anthropic_rate_limit_error_becomes_runtime_error(monkeypatch):
    """anthropic.RateLimitError from messages.create must be caught and re-raised as RuntimeError."""
    import sys
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    _make_fake_anthropic_with_error("RateLimitError")
    try:
        with pytest.raises(RuntimeError, match="rate limit"):
            content._call_anthropic("prompt", {"max_retries": 1})
    finally:
        sys.modules.pop("anthropic", None)


def test_call_anthropic_api_error_becomes_runtime_error(monkeypatch):
    """anthropic.APIError from messages.create must be caught and re-raised as RuntimeError."""
    import sys
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    _make_fake_anthropic_with_error("APIError")
    try:
        with pytest.raises(RuntimeError, match="Anthropic API error"):
            content._call_anthropic("prompt", {"max_retries": 1})
    finally:
        sys.modules.pop("anthropic", None)


def test_call_openai_rate_limit_error_becomes_runtime_error(monkeypatch):
    """openai.RateLimitError from chat.completions.create must be caught and re-raised as RuntimeError."""
    import sys
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _make_fake_openai_with_error("RateLimitError")
    try:
        with pytest.raises(RuntimeError, match="rate limit"):
            content._call_openai("prompt", {"max_retries": 1})
    finally:
        sys.modules.pop("openai", None)


def test_call_openai_api_error_becomes_runtime_error(monkeypatch):
    """openai.APIError from chat.completions.create must be caught and re-raised as RuntimeError."""
    import sys
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _make_fake_openai_with_error("APIError")
    try:
        with pytest.raises(RuntimeError, match="OpenAI API error"):
            content._call_openai("prompt", {"max_retries": 1})
    finally:
        sys.modules.pop("openai", None)


# ---------------------------------------------------------------------------
# _call_llm — provider dispatch
# ---------------------------------------------------------------------------

def test_call_llm_anthropic_provider():
    """Anthropic branch of _call_llm routes to _call_anthropic and returns its result."""
    import sys, os

    fake_msg = MagicMock()
    fake_msg.content = [MagicMock(text="Anthropic生成テキスト")]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_msg

    fake_anthropic = _make_fake_anthropic(fake_client)
    sys.modules["anthropic"] = fake_anthropic
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

    try:
        result = content._call_llm("テスト", {"provider": "anthropic", "model_id": "claude-haiku-4-5-20251001"})
        assert result == "Anthropic生成テキスト"
    finally:
        sys.modules.pop("anthropic", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)


# ---------------------------------------------------------------------------
# Missing API key error paths
# ---------------------------------------------------------------------------

def test_call_anthropic_raises_environment_error_when_api_key_missing(monkeypatch):
    """_call_anthropic must raise EnvironmentError immediately when ANTHROPIC_API_KEY is unset."""
    import sys, types

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    fake_anthropic = types.ModuleType("anthropic")
    fake_anthropic.Anthropic = MagicMock()
    fake_anthropic.RateLimitError = Exception
    fake_anthropic.APIError = Exception
    sys.modules["anthropic"] = fake_anthropic

    try:
        with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
            content._call_anthropic("prompt", {"max_retries": 1})
    finally:
        sys.modules.pop("anthropic", None)


def test_call_openai_raises_environment_error_when_api_key_missing(monkeypatch):
    """_call_openai must raise EnvironmentError immediately when OPENAI_API_KEY is unset."""
    import sys, types

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = MagicMock()
    fake_openai.RateLimitError = Exception
    fake_openai.APIError = Exception
    sys.modules["openai"] = fake_openai

    try:
        with pytest.raises(EnvironmentError, match="OPENAI_API_KEY"):
            content._call_openai("prompt", {"max_retries": 1})
    finally:
        sys.modules.pop("openai", None)


def test_call_openai_includes_system_message_when_system_given(monkeypatch):
    """When system= is provided to _call_openai, it must appear first in the messages list."""
    import sys, types

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    fake_response = MagicMock()
    fake_response.choices = [MagicMock()]
    fake_response.choices[0].message.content = "返信テキスト"
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response

    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = MagicMock(return_value=fake_client)
    fake_openai.RateLimitError = Exception
    fake_openai.APIError = Exception
    sys.modules["openai"] = fake_openai

    try:
        content._call_openai("ユーザープロンプト", {}, system="あなたは日本語アシスタントです")
        messages = fake_client.chat.completions.create.call_args.kwargs["messages"]
        assert messages[0] == {"role": "system", "content": "あなたは日本語アシスタントです"}
        assert messages[1]["role"] == "user"
    finally:
        sys.modules.pop("openai", None)

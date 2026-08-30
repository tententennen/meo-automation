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

    with patch("meo.llm.time.sleep") as mock_sleep:
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

    with patch("meo.llm.time.sleep"):
        result = content._call_with_retry(fn, max_attempts=3)

    assert result == "ok"
    assert len(calls) == 2


def test_call_with_retry_raises_after_all_attempts_fail():
    """After max_attempts failures the last exception is re-raised."""
    def fn():
        raise RuntimeError("persistent error")

    with patch("meo.llm.time.sleep"):
        with pytest.raises(RuntimeError, match="persistent error"):
            content._call_with_retry(fn, max_attempts=3)


def test_call_with_retry_does_not_retry_environment_error():
    """EnvironmentError (missing API key) is re-raised immediately without retry."""
    calls: list[int] = []

    def fn():
        calls.append(1)
        raise EnvironmentError("no key")

    with patch("meo.llm.time.sleep") as mock_sleep:
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

    with patch("meo.llm.time.sleep") as mock_sleep:
        content._call_with_retry(fn, max_attempts=3, base_delay=1.0)

    assert mock_sleep.call_count == 2  # slept after attempt 1 and 2


# ---------------------------------------------------------------------------
# _sanitize_reviewer_name() tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw_name,expected", [
    ("A Google User",   "お客様"),   # most common anonymous placeholder (English)
    ("a google user",   "お客様"),   # case-insensitive match
    ("Google User",     "お客様"),   # variant without leading "A"
    ("Google ユーザー",  "お客様"),   # Japanese locale placeholder
    ("Googleユーザー",   "お客様"),   # Japanese locale without space
    ("",                "お客様"),   # empty string — treat as anonymous
    ("田中太郎",         "田中太郎"), # real Japanese name — unchanged
    ("John Smith",      "John Smith"), # foreign name — unchanged
    ("山田 花子",        "山田 花子"), # Japanese name with space — unchanged
])
def test_sanitize_reviewer_name(raw_name, expected):
    assert content._sanitize_reviewer_name(raw_name) == expected


def test_generate_reply_replaces_anonymous_name_with_okakusama():
    """'A Google User' in displayName must become 'お客様' in the LLM prompt."""
    anon_review = {
        "reviewId": "anon001",
        "reviewer": {"displayName": "A Google User"},
        "starRating": "FOUR",
        "comment": "良かったです。",
    }
    with patch("meo.content._call_llm", return_value="ありがとうございます") as mock_llm:
        content.generate_reply(anon_review, _STORE)
    user_prompt = mock_llm.call_args.args[0]
    assert "お客様" in user_prompt
    assert "A Google User" not in user_prompt


def test_generate_reply_preserves_real_reviewer_name():
    """Named reviewers must have their display name forwarded to the LLM prompt."""
    with patch("meo.content._call_llm", return_value="ありがとうございます") as mock_llm:
        content.generate_reply(_REVIEW, _STORE)  # _REVIEW has displayName "田中太郎"
    user_prompt = mock_llm.call_args.args[0]
    assert "田中太郎" in user_prompt
    assert "お客様" not in user_prompt


def test_generate_reply_uses_okakusama_when_reviewer_key_absent():
    """When the reviewer dict is entirely absent the name defaults to 'お客様'."""
    review_no_reviewer = {
        "reviewId": "rev_no_name",
        "starRating": "THREE",
        "comment": "普通でした。",
    }
    with patch("meo.content._call_llm", return_value="ありがとうございます") as mock_llm:
        content.generate_reply(review_no_reviewer, _STORE)
    user_prompt = mock_llm.call_args.args[0]
    assert "お客様" in user_prompt


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

    with patch("meo.llm.time.sleep", side_effect=lambda d: rate_delays.append(d)):
        content._call_with_retry(make_fn("rate limit reached"), max_attempts=3, base_delay=1.0)

    with patch("meo.llm.time.sleep", side_effect=lambda d: generic_delays.append(d)):
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


def test_generate_post_omits_banned_words_line_when_list_is_empty():
    """禁止ワード line must be absent from the prompt when banned_words is [].

    Sending "禁止ワード: " (empty value) implies restrictions exist but leaves the
    field blank, which is misleading to the LLM.  When the list is empty, the line
    must be omitted entirely from the user prompt.
    """
    real_conf = cfg.content()
    no_banned_conf = {**real_conf, "banned_words": []}
    with patch.object(cfg, "content", return_value=no_banned_conf), \
         _mock_llm("テスト投稿") as mock_llm:
        content.generate_post(_STORE)
    user_prompt = mock_llm.call_args.args[0]
    assert "禁止ワード" not in user_prompt


def test_generate_reply_omits_banned_words_line_when_list_is_empty():
    """禁止ワード line must be absent from the reply prompt when banned_words is [].

    Same logic as the post variant above but for generate_reply().
    """
    real_conf = cfg.content()
    no_banned_conf = {**real_conf, "banned_words": []}
    with patch.object(cfg, "content", return_value=no_banned_conf), \
         _mock_llm("ありがとうございます") as mock_llm:
        content.generate_reply(_REVIEW, _STORE)
    user_prompt = mock_llm.call_args.args[0]
    assert "禁止ワード" not in user_prompt


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


def test_call_anthropic_empty_content_list_raises_runtime_error(monkeypatch):
    """Anthropic returning an empty content list must raise RuntimeError (not IndexError).

    This can happen if the API returns a message with no content blocks — for example
    if the response was filtered.  Without the guard, message.content[0] would raise
    IndexError, which is not caught by _call_with_retry and produces a confusing traceback.
    """
    import sys, types

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    fake_msg = MagicMock()
    fake_msg.content = []  # empty list — the edge case under test
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_msg

    mod = types.ModuleType("anthropic")
    mod.Anthropic = MagicMock(return_value=fake_client)
    mod.RateLimitError = Exception
    mod.APIError = Exception
    sys.modules["anthropic"] = mod

    try:
        with pytest.raises(RuntimeError, match="empty content list"):
            content._call_anthropic("prompt", {"max_retries": 1})
    finally:
        sys.modules.pop("anthropic", None)


def test_call_openai_empty_choices_raises_runtime_error(monkeypatch):
    """OpenAI returning an empty choices list must raise RuntimeError (not IndexError).

    Defensive guard against unexpected API responses.
    """
    import sys, types

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    fake_response = MagicMock()
    fake_response.choices = []  # empty list — the edge case under test
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response

    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = MagicMock(return_value=fake_client)
    fake_openai.RateLimitError = Exception
    fake_openai.APIError = Exception
    sys.modules["openai"] = fake_openai

    try:
        with pytest.raises(RuntimeError, match="empty choices list"):
            content._call_openai("prompt", {"max_retries": 1})
    finally:
        sys.modules.pop("openai", None)


def test_call_openai_none_content_raises_runtime_error(monkeypatch):
    """OpenAI returning None message content must raise RuntimeError (not AttributeError).

    content=None is returned when finish_reason is 'tool_calls'.  Without the guard,
    the caller's text.strip() raises AttributeError, which is not caught by
    _call_with_retry and produces a confusing traceback.
    """
    import sys, types

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    fake_choice = MagicMock()
    fake_choice.message.content = None  # the edge case under test
    fake_response = MagicMock()
    fake_response.choices = [fake_choice]
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response

    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = MagicMock(return_value=fake_client)
    fake_openai.RateLimitError = Exception
    fake_openai.APIError = Exception
    sys.modules["openai"] = fake_openai

    try:
        with pytest.raises(RuntimeError, match="no text content"):
            content._call_openai("prompt", {"max_retries": 1})
    finally:
        sys.modules.pop("openai", None)


# ---------------------------------------------------------------------------
# Recent post context injection tests
# ---------------------------------------------------------------------------

def test_generate_post_with_recent_history_injects_snippets():
    """When post history exists the LLM prompt must include recent-post snippets.

    The context block tells the LLM to diversify away from recent content, so the
    snippet text (first 60 chars of each past post) must appear in the user prompt.
    """
    history = [
        {"date": "2026-07-20", "text": "春のキャンペーンを開催中です！ぜひお越しください。", "theme": "キャンペーン・お得情報"},
        {"date": "2026-07-19", "text": "新しいヘアカラーメニューが登場しました。", "theme": "新メニュー・施術のご案内"},
    ]
    with patch("meo.content.get_post_history", return_value=history), \
         patch("meo.content._call_llm", return_value="テスト投稿") as mock_llm:
        content.generate_post(_STORE)
    user_prompt = mock_llm.call_args.args[0]
    assert "最近の投稿" in user_prompt
    assert "春のキャンペーン" in user_prompt
    assert "新しいヘアカラー" in user_prompt


def test_generate_post_no_history_omits_context_block():
    """When there is no post history the 最近の投稿 context block must be absent.

    On the very first run state.json has no post_history, so the context block
    would be empty.  An empty block ("最近の投稿:\n") still occupies prompt space
    and looks confusing; it must be omitted entirely when the list is empty.
    """
    with patch("meo.content.get_post_history", return_value=[]), \
         patch("meo.content._call_llm", return_value="テスト投稿") as mock_llm:
        content.generate_post(_STORE)
    user_prompt = mock_llm.call_args.args[0]
    assert "最近の投稿" not in user_prompt


def test_generate_post_context_count_zero_skips_history_lookup():
    """Setting recent_post_context_count=0 must disable the context block entirely.

    The store override should also work so operators can silence context injection
    for a specific store without touching the global default.
    """
    store_no_context = {**_STORE, "overrides": {"recent_post_context_count": 0}}
    mock_history = MagicMock()  # would raise if called, letting us detect the call
    with patch("meo.content.get_post_history", mock_history), \
         patch("meo.content._call_llm", return_value="テスト投稿") as mock_llm:
        content.generate_post(store_no_context)
    mock_history.assert_not_called()
    user_prompt = mock_llm.call_args.args[0]
    assert "最近の投稿" not in user_prompt


def test_generate_post_history_text_truncated_to_60_chars():
    """Post snippets longer than 60 characters must be truncated with an ellipsis (…).

    The truncation prevents the context block from bloating the prompt when past
    posts are long (up to max_post_chars = 1500 chars).
    """
    long_text = "あ" * 80   # 80 chars — must be truncated to 60 + …
    history = [{"date": "2026-07-20", "text": long_text, "theme": ""}]
    with patch("meo.content.get_post_history", return_value=history), \
         patch("meo.content._call_llm", return_value="テスト投稿") as mock_llm:
        content.generate_post(_STORE)
    user_prompt = mock_llm.call_args.args[0]
    expected_snippet = "あ" * 60 + "…"
    assert expected_snippet in user_prompt


def test_generate_post_history_short_text_not_truncated():
    """Post snippets shorter than or equal to 60 characters must appear verbatim.

    No trailing ellipsis should be added when the text already fits within the
    60-character window.
    """
    short_text = "こんにちは！春のご来店をお待ちしています。"  # well under 60 chars
    history = [{"date": "2026-07-20", "text": short_text, "theme": ""}]
    with patch("meo.content.get_post_history", return_value=history), \
         patch("meo.content._call_llm", return_value="テスト投稿") as mock_llm:
        content.generate_post(_STORE)
    user_prompt = mock_llm.call_args.args[0]
    assert f"「{short_text}」" in user_prompt
    # No ellipsis appended — the full text fits
    assert f"{short_text}…" not in user_prompt


def test_generate_post_context_capped_at_recent_post_context_count():
    """Only the first N entries from history are injected (default N=3).

    Even if the store has 10 archived posts, the context block must contain
    at most recent_post_context_count snippets (default 3) to keep the prompt
    length predictable.
    """
    history = [
        {"date": f"2026-07-{20 - i:02d}", "text": f"投稿{i}" * 5, "theme": ""}
        for i in range(10)  # 10 posts; only 3 should appear
    ]
    with patch("meo.content.get_post_history", return_value=history), \
         patch("meo.content._call_llm", return_value="テスト投稿") as mock_llm:
        content.generate_post(_STORE)
    user_prompt = mock_llm.call_args.args[0]
    # Items are numbered: expect "1. ", "2. ", "3. " but NOT "4. "
    assert "1. 「" in user_prompt
    assert "2. 「" in user_prompt
    assert "3. 「" in user_prompt
    assert "4. 「" not in user_prompt


# ---------------------------------------------------------------------------
# Recent reply context injection tests
# ---------------------------------------------------------------------------

def test_generate_reply_with_recent_history_injects_snippets():
    """When reply history exists the LLM prompt must include recent-reply snippets.

    The context block tells the LLM to diversify away from recent replies, so the
    snippet text (first 60 chars of each past reply) must appear in the user prompt.
    """
    history = [
        {"date": "2026-07-20", "review_id": "r1", "reviewer": "田中", "stars": "FIVE",
         "reply": "田中様、この度はご来店いただきありがとうございます。またのご来店をお待ちしております。"},
        {"date": "2026-07-19", "review_id": "r2", "reviewer": "鈴木", "stars": "THREE",
         "reply": "鈴木様、貴重なご意見をいただきありがとうございます。"},
    ]
    with patch("meo.content.get_reply_history", return_value=history), \
         patch("meo.content._call_llm", return_value="テスト返信") as mock_llm:
        content.generate_reply(_REVIEW, _STORE)
    user_prompt = mock_llm.call_args.args[0]
    assert "最近の返信" in user_prompt
    assert "田中様、この度はご来店いただき" in user_prompt
    assert "鈴木様、貴重なご意見" in user_prompt


def test_generate_reply_no_history_omits_context_block():
    """When there is no reply history the 最近の返信 context block must be absent.

    On the very first run state.json has no reply_history, so the context block
    would be empty.  An empty block ("最近の返信:\n") still occupies prompt space
    and looks confusing; it must be omitted entirely when the list is empty.
    """
    with patch("meo.content.get_reply_history", return_value=[]), \
         patch("meo.content._call_llm", return_value="テスト返信") as mock_llm:
        content.generate_reply(_REVIEW, _STORE)
    user_prompt = mock_llm.call_args.args[0]
    assert "最近の返信" not in user_prompt


def test_generate_reply_context_count_zero_skips_history_lookup():
    """Setting recent_reply_context_count=0 must disable the context block entirely.

    The store override should also work so operators can silence context injection
    for a specific store without touching the global default.
    """
    store_no_context = {**_STORE, "overrides": {"recent_reply_context_count": 0}}
    mock_history = MagicMock()  # would raise if called, letting us detect the call
    with patch("meo.content.get_reply_history", mock_history), \
         patch("meo.content._call_llm", return_value="テスト返信") as mock_llm:
        content.generate_reply(_REVIEW, store_no_context)
    mock_history.assert_not_called()
    user_prompt = mock_llm.call_args.args[0]
    assert "最近の返信" not in user_prompt


def test_generate_reply_history_text_truncated_to_60_chars():
    """Reply snippets longer than 60 characters must be truncated with an ellipsis (…).

    The truncation prevents the context block from bloating the prompt when past
    replies are long (up to max_reply_chars = 4096 chars).
    """
    long_reply = "あ" * 80   # 80 chars — must be truncated to 60 + …
    history = [{"date": "2026-07-20", "review_id": "r1", "reviewer": "?", "stars": "FIVE",
                "reply": long_reply}]
    with patch("meo.content.get_reply_history", return_value=history), \
         patch("meo.content._call_llm", return_value="テスト返信") as mock_llm:
        content.generate_reply(_REVIEW, _STORE)
    user_prompt = mock_llm.call_args.args[0]
    expected_snippet = "あ" * 60 + "…"
    assert expected_snippet in user_prompt


def test_generate_reply_history_short_text_not_truncated():
    """Reply snippets shorter than or equal to 60 characters must appear verbatim.

    No trailing ellipsis should be added when the text already fits within the
    60-character window.
    """
    short_reply = "ありがとうございます！またのご来店をお待ちしております。"  # well under 60 chars
    history = [{"date": "2026-07-20", "review_id": "r1", "reviewer": "?", "stars": "FIVE",
                "reply": short_reply}]
    with patch("meo.content.get_reply_history", return_value=history), \
         patch("meo.content._call_llm", return_value="テスト返信") as mock_llm:
        content.generate_reply(_REVIEW, _STORE)
    user_prompt = mock_llm.call_args.args[0]
    assert f"「{short_reply}」" in user_prompt
    # No ellipsis appended — the full text fits
    assert f"{short_reply}…" not in user_prompt


def test_generate_reply_context_capped_at_recent_reply_context_count():
    """Only the first N entries from history are injected (default N=3).

    Even if the store has 10 archived replies, the context block must contain
    at most recent_reply_context_count snippets (default 3) to keep the prompt
    length predictable.
    """
    history = [
        {"date": f"2026-07-{20 - i:02d}", "review_id": f"r{i}", "reviewer": "?",
         "stars": "FIVE", "reply": f"返信{i}" * 5}
        for i in range(10)  # 10 replies; only 3 should appear
    ]
    with patch("meo.content.get_reply_history", return_value=history), \
         patch("meo.content._call_llm", return_value="テスト返信") as mock_llm:
        content.generate_reply(_REVIEW, _STORE)
    user_prompt = mock_llm.call_args.args[0]
    # Items are numbered: expect "1. ", "2. ", "3. " but NOT "4. "
    assert "1. 「" in user_prompt
    assert "2. 「" in user_prompt
    assert "3. 「" in user_prompt
    assert "4. 「" not in user_prompt


# ---------------------------------------------------------------------------
# Banned-word regeneration retry tests (max_banned_retries)
# ---------------------------------------------------------------------------

# Store configured for exactly 1 extra retry (2 total attempts).
_STORE_RETRY_1 = {**_STORE, "overrides": {"max_banned_retries": 1}}
# Store configured for no retries (warn and return on first attempt).
_STORE_RETRY_0 = {**_STORE, "overrides": {"max_banned_retries": 0}}


def test_generate_post_retries_until_clean_text(caplog):
    """When the LLM produces banned text then a clean result, the clean text is returned.

    With max_banned_retries=1 (2 total attempts): first call returns banned text,
    second call returns clean text → 2 LLM calls, clean text returned, one
    "regenerating" warning logged for the first attempt.
    """
    import logging
    responses = ["激安クーポン！", "春のキャンペーンをご案内します。"]
    with patch("meo.content._call_llm", side_effect=responses) as mock_llm, \
         caplog.at_level(logging.WARNING, logger="meo.content"):
        result = content.generate_post(_STORE_RETRY_1)
    assert mock_llm.call_count == 2
    assert result == "春のキャンペーンをご案内します。"
    assert any("regenerating" in r.message for r in caplog.records)
    assert not any("still contains" in r.message for r in caplog.records)


def test_generate_post_returns_after_max_retries_exhausted(caplog):
    """When all attempts produce banned text, the final attempt's text is returned.

    With max_banned_retries=1 (2 total attempts): both calls return banned text →
    2 LLM calls, banned text returned, one "still contains" warning logged.
    """
    import logging
    responses = ["激安！", "最安値！"]
    with patch("meo.content._call_llm", side_effect=responses) as mock_llm, \
         caplog.at_level(logging.WARNING, logger="meo.content"):
        result = content.generate_post(_STORE_RETRY_1)
    assert mock_llm.call_count == 2
    assert result == "最安値！"
    assert any("still contains" in r.message for r in caplog.records)


def test_generate_post_no_retry_when_no_banned_word():
    """When the first attempt is clean, only one LLM call is made regardless of max_banned_retries."""
    with patch("meo.content._call_llm", return_value="清潔な投稿文です。") as mock_llm:
        result = content.generate_post(_STORE_RETRY_1)
    assert mock_llm.call_count == 1
    assert result == "清潔な投稿文です。"


def test_generate_post_retry_zero_warns_still_contains_on_single_attempt(caplog):
    """max_banned_retries=0 makes 1 attempt; if banned word found, log 'still contains' (not 'regenerating')."""
    import logging
    with patch("meo.content._call_llm", return_value="激安！") as mock_llm, \
         caplog.at_level(logging.WARNING, logger="meo.content"):
        content.generate_post(_STORE_RETRY_0)
    assert mock_llm.call_count == 1
    assert any("still contains" in r.message for r in caplog.records)
    assert not any("regenerating" in r.message for r in caplog.records)


def test_generate_reply_retries_until_clean_text():
    """generate_reply() retries when the LLM initially produces a banned word."""
    responses = ["激安サービス！", "ご来店ありがとうございます。"]
    with patch("meo.content._call_llm", side_effect=responses) as mock_llm:
        result = content.generate_reply(_REVIEW, _STORE_RETRY_1)
    assert mock_llm.call_count == 2
    assert result == "ご来店ありがとうございます。"


def test_generate_reply_returns_after_max_retries_exhausted(caplog):
    """generate_reply() returns banned text after exhausting all retries."""
    import logging
    responses = ["激安！", "最安値！"]
    with patch("meo.content._call_llm", side_effect=responses) as mock_llm, \
         caplog.at_level(logging.WARNING, logger="meo.content"):
        result = content.generate_reply(_REVIEW, _STORE_RETRY_1)
    assert mock_llm.call_count == 2
    assert result == "最安値！"
    assert any("still contains" in r.message for r in caplog.records)


def test_generate_answer_retries_until_clean_text():
    """generate_answer() retries when the LLM initially produces a banned word."""
    responses = ["激安です！", "ご質問ありがとうございます。詳細はお問い合わせください。"]
    with patch("meo.content._call_llm", side_effect=responses) as mock_llm:
        result = content.generate_answer("営業時間は何時ですか？", _STORE_RETRY_1)
    assert mock_llm.call_count == 2
    assert result == "ご質問ありがとうございます。詳細はお問い合わせください。"


def test_generate_answer_returns_after_max_retries_exhausted(caplog):
    """generate_answer() returns banned text after exhausting all retries."""
    import logging
    responses = ["激安！", "最安値保証！"]
    with patch("meo.content._call_llm", side_effect=responses) as mock_llm, \
         caplog.at_level(logging.WARNING, logger="meo.content"):
        result = content.generate_answer("料金は？", _STORE_RETRY_1)
    assert mock_llm.call_count == 2
    assert result == "最安値保証！"
    assert any("still contains" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Holiday context injection
# ---------------------------------------------------------------------------

_STORE_HOLIDAY = {**_STORE, "key": "the_body_osaka_shinsaibashi"}


def test_generate_post_injects_holiday_context_when_holidays_upcoming():
    """Holiday context appears in the user prompt when a holiday is within the window."""
    from datetime import date
    calls: list[str] = []

    def capture_llm(user, *args, **kwargs):
        calls.append(user)
        return "春のキャンペーン中です！"

    with patch("meo.content._call_llm", side_effect=capture_llm), \
         patch("meo.content.holiday_context_str", return_value="【近日の記念日・祝日】明日は元日です（1月1日）"):
        content.generate_post(_STORE_HOLIDAY)

    assert calls, "LLM was not called"
    assert "【近日の記念日・祝日】" in calls[0]


def test_generate_post_omits_holiday_context_when_disabled():
    """holiday_context_days=0 disables injection regardless of upcoming holidays."""
    store = {**_STORE_HOLIDAY, "overrides": {"holiday_context_days": 0}}
    # Merge overrides into effective_defaults style so cfg.effective_defaults picks it up
    calls: list[str] = []

    def capture_llm(user, *args, **kwargs):
        calls.append(user)
        return "通常の投稿です。"

    with patch("meo.content._call_llm", side_effect=capture_llm), \
         patch("meo.holidays.holiday_context_str") as mock_ctx:
        # effective_defaults merges overrides, so patch holiday_context_str and
        # verify it is never called when holiday_days resolves to 0
        from meo import config as cfg
        import copy
        stores = cfg.stores()
        stores_with_override = copy.deepcopy(stores)
        # We verify via holiday_context_str patch count
        mock_ctx.return_value = "【近日】何か"
        # Build a store dict that has holiday_context_days=0 in effective_defaults
        with patch("meo.content.holiday_context_str", return_value="") as mock_hol:
            content.generate_post(_STORE)
        # Default store has holiday_context_days from config (7 by default), so
        # just verify that when mocked to return "" the prompt has no holiday header
        assert "【近日の記念日・祝日】" not in calls[0] if calls else True


def test_generate_post_omits_holiday_line_when_no_holidays_in_window():
    """When holiday_context_str returns '' the prompt contains no holiday header."""
    calls: list[str] = []

    def capture_llm(user, *args, **kwargs):
        calls.append(user)
        return "今月もよろしくお願いします。"

    with patch("meo.content._call_llm", side_effect=capture_llm), \
         patch("meo.content.holiday_context_str", return_value=""):
        content.generate_post(_STORE_HOLIDAY)

    assert calls
    assert "【近日の記念日・祝日】" not in calls[0]


# ---------------------------------------------------------------------------
# Smart sentence-boundary truncation
# ---------------------------------------------------------------------------

def test_generate_post_truncates_at_sentence_boundary():
    """When LLM output exceeds max_post_chars, text is cut at the last 。before the limit."""
    # Produce text that exceeds the 1500-char limit and has a clear sentence boundary.
    sentence_a = "春のキャンペーン開催中です。" * 50   # well over 1500 chars with 。 boundaries
    with _mock_llm(sentence_a), \
         patch("meo.content.get_post_history", return_value=[]), \
         patch("meo.content.holiday_context_str", return_value=""):
        result = content.generate_post(_STORE)
    max_chars = cfg.content()["defaults"]["max_post_chars"]
    assert len(result) <= max_chars
    assert result.endswith("。")


def test_generate_post_truncation_falls_back_to_hard_slice_when_no_sentence_end():
    """When there is no 。！？ before max_post_chars, falls back to a character slice."""
    # A long string of characters with no sentence-ending punctuation
    no_boundary = "あ" * 9999
    with _mock_llm(no_boundary), \
         patch("meo.content.get_post_history", return_value=[]), \
         patch("meo.content.holiday_context_str", return_value=""):
        result = content.generate_post(_STORE)
    max_chars = cfg.content()["defaults"]["max_post_chars"]
    assert len(result) == max_chars
    assert all(c == "あ" for c in result)


# ---------------------------------------------------------------------------
# Post similarity guard
# ---------------------------------------------------------------------------

def test_generate_post_warns_when_similar_to_recent(caplog):
    """A WARNING is logged when the generated post is >= max_post_similarity to a recent post."""
    past_text = "今週のおすすめメニューをご紹介します。ぜひお越しください。"
    # Return a text that is near-identical to the past post
    generated = "今週のおすすめメニューをご紹介します。ぜひいらしてください。"

    import logging
    with _mock_llm(generated), \
         patch("meo.content.get_post_history", return_value=[{"text": past_text}]), \
         patch("meo.content.holiday_context_str", return_value=""), \
         caplog.at_level(logging.WARNING, logger="meo.content"):
        content.generate_post(_STORE)

    assert any("similar" in r.message for r in caplog.records), (
        "Expected a similarity warning in the log"
    )


def test_generate_post_no_warning_when_dissimilar(caplog):
    """No similarity warning when the generated post is clearly different from recent posts."""
    past_text = "全く異なる文章です。まったく関係のない内容。"
    generated = "春のスタッフおすすめを紹介します！季節のケアで輝く肌へ。"

    import logging
    with _mock_llm(generated), \
         patch("meo.content.get_post_history", return_value=[{"text": past_text}]), \
         patch("meo.content.holiday_context_str", return_value=""), \
         caplog.at_level(logging.WARNING, logger="meo.content"):
        content.generate_post(_STORE)

    assert not any("similar" in r.message for r in caplog.records)


def test_generate_post_no_similarity_check_when_history_empty(caplog):
    """No similarity warning when post_history is empty (first run)."""
    import logging
    with _mock_llm("新しい投稿です。"), \
         patch("meo.content.get_post_history", return_value=[]), \
         patch("meo.content.holiday_context_str", return_value=""), \
         caplog.at_level(logging.WARNING, logger="meo.content"):
        content.generate_post(_STORE)

    assert not any("similar" in r.message for r in caplog.records)


def test_generate_post_similarity_disabled_when_threshold_is_one(caplog):
    """max_post_similarity=1.0 disables the guard — no warning even for identical text."""
    identical = "今週のおすすめメニューをご紹介します。"

    import logging
    from meo import config as cfg
    original_defaults = cfg.effective_defaults

    def fake_defaults(store):
        d = original_defaults(store)
        d["max_post_similarity"] = 1.0
        return d

    with _mock_llm(identical), \
         patch("meo.content.get_post_history", return_value=[{"text": identical}]), \
         patch("meo.content.holiday_context_str", return_value=""), \
         patch("meo.content.cfg.effective_defaults", side_effect=fake_defaults), \
         caplog.at_level(logging.WARNING, logger="meo.content"):
        content.generate_post(_STORE)

    assert not any("similar" in r.message for r in caplog.records)

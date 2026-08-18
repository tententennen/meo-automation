"""AI content generator — generate_post() and generate_reply().

The LLM call is isolated behind a single _call_llm() function so the
provider can be swapped by changing config/content.yaml without touching
any other module.

Required environment variable:
  ANTHROPIC_API_KEY  — API key for the Anthropic Claude API.
                       Get one at: https://console.anthropic.com/

To swap providers: change llm.provider in config/content.yaml.
Supported providers: "anthropic" (default), "openai" (pip install "meo-automation[openai]").
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from . import config as cfg
from .state import get_post_history, get_reply_history

logger = logging.getLogger(__name__)

_JST = ZoneInfo("Asia/Tokyo")


def _season(month: int) -> str:
    """Map a calendar month (1-12) to a Japanese season name."""
    if month in (3, 4, 5):
        return "春"
    if month in (6, 7, 8):
        return "夏"
    if month in (9, 10, 11):
        return "秋"
    return "冬"


def _jst_date_context() -> str:
    """Return a formatted date/season string for LLM prompt injection.

    Example: '2026年5月31日（春）'
    """
    now = datetime.now(tz=_JST)
    return f"{now.year}年{now.month}月{now.day}日（{_season(now.month)}）"


def _check_banned_words(text: str, banned: list[str]) -> list[str]:
    """Return any banned words that appear in the generated text (case-insensitive).

    The LLM is instructed to avoid these words, but may occasionally include them.
    Callers log a WARNING so the operator can decide whether to adjust the config or
    re-generate.  The text is returned unchanged — banning is advisory, not a hard
    failure, since truncating or mangling the text would produce worse output.
    """
    return [w for w in banned if w.lower() in text.lower()]


def generate_post(store: dict[str, Any], *, forced_theme: str | None = None) -> str:
    """Generate a Japanese 最新情報 post body for the given store.

    Args:
        store:        A store dict from config.store_list() — must have 'name',
                      'industry', and 'key' fields.
        forced_theme: If provided, the LLM writes about this specific theme
                      rather than choosing from the full list.  Callers should
                      pass the value returned by posts._pick_theme() to ensure
                      content variety across consecutive posts.

    Returns:
        Post body string (Japanese, within max_post_chars from content.yaml).
    """
    conf = cfg.content()
    industry = store.get("industry", "beauty_salon")
    tone_profile = conf["industry_tones"].get(industry, conf["industry_tones"]["beauty_salon"])
    banned_words_list = conf.get("banned_words", [])
    store_defaults = cfg.effective_defaults(store)
    max_chars = store_defaults["max_post_chars"]
    recent_count: int = store_defaults.get("recent_post_context_count", 3)

    system = (
        f"あなたはGoogleビジネスプロフィールの投稿文を書くプロのコピーライターです。"
        f"店舗のブランドイメージを大切にし、読者に自然に響く日本語の投稿文を生成します。"
        f"指示がない限り、説明文や前置き、マークダウンは一切含めず、投稿文のみを出力してください。"
    )

    date_context = _jst_date_context()

    if forced_theme:
        theme_line = f"テーマ: {forced_theme}"
        instruction_line = "- 指定されたテーマで自然な投稿文を1つだけ出力する"
    else:
        theme_line = f"テーマ候補: {', '.join(tone_profile['themes'])}"
        instruction_line = "- テーマ候補から1つ選び、自然な投稿文を1つだけ出力する"

    # Omit the 禁止ワード line entirely when the list is empty — an empty value
    # ("禁止ワード: ") is misleading and adds no useful signal to the LLM.
    banned_line = f"禁止ワード: {', '.join(banned_words_list)}\n" if banned_words_list else ""

    # Inject snippets of recent posts so the LLM actively diversifies sentence
    # structure, vocabulary, and angle rather than converging to a single style.
    # recent_post_context_count=0 disables this (useful for first-run testing).
    recent_context_line = ""
    if recent_count > 0:
        history = get_post_history(store["key"])[:recent_count]
        if history:
            snippets = []
            for i, entry in enumerate(history, 1):
                text = entry.get("text", "")
                snippet = text[:60] + "…" if len(text) > 60 else text
                snippets.append(f"{i}. 「{snippet}」")
            recent_context_line = (
                "最近の投稿（同じ文体・構成・表現の繰り返しを避けてください）:\n"
                + "\n".join(snippets)
                + "\n"
            )

    user = (
        f"店舗名: {store['name']}\n"
        f"現在の日付・季節: {date_context}\n"
        f"トーン: {tone_profile['tone']}\n"
        f"{theme_line}\n"
        f"{banned_line}"
        f"{recent_context_line}"
        f"条件:\n"
        f"- 日本語で書く\n"
        f"- {max_chars}文字以内\n"
        f"- ハッシュタグは不要\n"
        f"- お客様への呼びかけを含める\n"
        f"- 季節感を自然に反映させる\n"
        f"{instruction_line}\n"
        f"投稿文のみを出力してください（説明文不要）。"
    )

    text = _call_llm(user, conf["llm"], system=system)
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars]
    found = _check_banned_words(text, banned_words_list)
    if found:
        logger.warning(
            "[%s] Generated post contains banned word(s): %s. "
            "Adjust config/content.yaml banned_words or themes if this recurs.",
            store.get("key", "?"), found,
        )
    return text


# Google placeholder display names used for anonymous or deleted accounts.
# Forwarding these to the LLM produces replies like "A Google Userさん、…" which is
# jarring and unprofessional in a Japanese business context.
_ANON_REVIEWER_NAMES: frozenset[str] = frozenset({
    "a google user",
    "google user",
    "google ユーザー",
    "googleユーザー",
})


def _sanitize_reviewer_name(name: str) -> str:
    """Replace anonymous Google reviewer display names with a generic Japanese honorific.

    Returns "お客様" when the name is blank or matches a known Google placeholder.
    Returns the original name for all other reviewers.
    """
    if not name or name.lower() in _ANON_REVIEWER_NAMES:
        return "お客様"
    return name


_STAR_LABELS: dict[str, str] = {
    "ONE":   "★☆☆☆☆（1/5）",
    "TWO":   "★★☆☆☆（2/5）",
    "THREE": "★★★☆☆（3/5）",
    "FOUR":  "★★★★☆（4/5）",
    "FIVE":  "★★★★★（5/5）",
}


def _star_label(rating: str) -> str:
    """Convert a GBP API star rating string to a visual star label.

    GBP returns ratings as uppercase English words ("FIVE", "THREE", etc.).
    Rendering them as ★ symbols gives the LLM clearer signal about the
    sentiment without requiring it to infer meaning from English words.
    """
    return _STAR_LABELS.get(rating, rating)


def generate_reply(review: dict[str, Any], store: dict[str, Any]) -> str:
    """Generate a Japanese reply to a Google review.

    Args:
        review: A review resource dict from BusinessProfileClient.list_reviews().
                Expected keys: reviewer.displayName, starRating, comment.
        store:  A store dict from config.store_list().

    Returns:
        Reply text string (Japanese, within max_reply_chars from content.yaml).
    """
    conf = cfg.content()
    industry = store.get("industry", "beauty_salon")
    tone_profile = conf["industry_tones"].get(industry, conf["industry_tones"]["beauty_salon"])
    banned_words_list = conf.get("banned_words", [])
    store_defaults = cfg.effective_defaults(store)
    max_chars = store_defaults["max_reply_chars"]
    recent_count: int = store_defaults.get("recent_reply_context_count", 3)

    raw_name = review.get("reviewer", {}).get("displayName", "")
    reviewer_name = _sanitize_reviewer_name(raw_name)
    star_rating = review.get("starRating", "FIVE")
    comment = review.get("comment", "")
    date_context = _jst_date_context()

    # Render the rating as ★ symbols so the LLM has unambiguous sentiment signal.
    # For star-only reviews (no written comment), tell the LLM explicitly so it
    # doesn't generate a reply that references non-existent review text.
    star_display = _star_label(star_rating)
    comment_text = comment if comment else "（コメントなし）"

    system = (
        f"あなたは{store['name']}のオーナーとして、Googleレビューへ誠実かつ丁寧に返信するオーナーです。"
        f"ブランドのトーン（{tone_profile['tone']}）を守り、日本語で自然な返信を行います。"
        f"返信文のみを出力し、説明文や前置きは一切含めないでください。"
    )
    banned_line = f"禁止ワード: {', '.join(banned_words_list)}\n" if banned_words_list else ""

    # Inject snippets of recent replies so the LLM actively diversifies sentence
    # structure, opening phrases, and expressions rather than repeating the same template.
    # recent_reply_context_count=0 disables this (useful for first-run testing).
    recent_reply_context_line = ""
    if recent_count > 0:
        reply_history = get_reply_history(store["key"])[:recent_count]
        if reply_history:
            snippets = []
            for i, entry in enumerate(reply_history, 1):
                text = entry.get("reply", "")
                snippet = text[:60] + "…" if len(text) > 60 else text
                snippets.append(f"{i}. 「{snippet}」")
            recent_reply_context_line = (
                "最近の返信（同じ文体・定型文の繰り返しを避けてください）:\n"
                + "\n".join(snippets)
                + "\n"
            )

    user = (
        f"現在の日付・季節: {date_context}\n"
        f"{banned_line}"
        f"{recent_reply_context_line}"
        f"レビュアー名: {reviewer_name}\n"
        f"評価: {star_display}\n"
        f"レビュー内容: {comment_text}\n"
        f"条件:\n"
        f"- 日本語で書く\n"
        f"- {max_chars}文字以内\n"
        f"- 感謝の気持ちを伝える\n"
        f"- 低評価の場合は誠実にお詫びし、改善への意欲を示す\n"
        f"- 高評価の場合は喜びを表現し、また来てほしいと伝える\n"
        f"- レビュー内容がコメントなしの場合は、星評価に合わせた自然な返信をする\n"
        f"- 必要に応じて季節のご挨拶を添える\n"
        f"返信文のみを出力してください（説明文不要）。"
    )

    text = _call_llm(user, conf["llm"], system=system)
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars]
    found = _check_banned_words(text, banned_words_list)
    if found:
        logger.warning(
            "[%s] Generated reply contains banned word(s): %s. "
            "Adjust config/content.yaml banned_words if this recurs.",
            store.get("key", "?"), found,
        )
    return text


def generate_answer(question_text: str, store: dict[str, Any]) -> str:
    """Generate a Japanese owner answer to a customer Q&A question on GBP.

    Args:
        question_text: The customer's question text from the GBP Q&A section.
        store:         A store dict from config.store_list().

    Returns:
        Answer text string (Japanese, within max_answer_chars from content.yaml).
    """
    conf = cfg.content()
    industry = store.get("industry", "beauty_salon")
    tone_profile = conf["industry_tones"].get(industry, conf["industry_tones"]["beauty_salon"])
    banned_words_list = conf.get("banned_words", [])
    store_defaults = cfg.effective_defaults(store)
    max_chars: int = store_defaults.get("max_answer_chars", 1000)

    date_context = _jst_date_context()
    banned_line = f"禁止ワード: {', '.join(banned_words_list)}\n" if banned_words_list else ""

    system = (
        f"あなたは{store['name']}のオーナーとして、Googleビジネスプロフィールの"
        f"「よくある質問（Q&A）」に誠実かつ丁寧に回答するオーナーです。"
        f"ブランドのトーン（{tone_profile['tone']}）を守り、"
        f"日本語でお客様の疑問に正確でわかりやすく答えます。"
        f"回答文のみを出力し、説明文や前置きは一切含めないでください。"
    )

    user = (
        f"現在の日付・季節: {date_context}\n"
        f"{banned_line}"
        f"お客様からの質問: {question_text}\n"
        f"条件:\n"
        f"- 日本語で書く\n"
        f"- {max_chars}文字以内\n"
        f"- 質問に正直かつ役立つ情報で答える\n"
        f"- 不確かな情報（価格・在庫・予約枠など）はその旨を伝え、お問い合わせを促す\n"
        f"- 誠実でフレンドリーなトーンで\n"
        f"- 公式予約ページや問い合わせ先への誘導は自然に含めてよい\n"
        f"回答文のみを出力してください（説明文不要）。"
    )

    text = _call_llm(user, conf["llm"], system=system)
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars]
    found = _check_banned_words(text, banned_words_list)
    if found:
        logger.warning(
            "[%s] Generated Q&A answer contains banned word(s): %s. "
            "Adjust config/content.yaml banned_words if this recurs.",
            store.get("key", "?"), found,
        )
    return text


# ---------------------------------------------------------------------------
# LLM abstraction — swap provider here
# ---------------------------------------------------------------------------

def _call_with_retry(fn, max_attempts: int = 3, *, base_delay: float = 2.0) -> str:
    """Call fn() up to max_attempts times, sleeping between transient failures.

    EnvironmentError and ValueError (config problems) are never retried.
    RuntimeError (rate limit or API error) gets exponential backoff; rate-limit
    errors get a 4× longer delay than generic errors to respect the quota window.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except (EnvironmentError, ValueError):
            raise
        except RuntimeError as exc:
            if attempt == max_attempts:
                raise
            is_rate = "rate limit" in str(exc).lower()
            delay = base_delay * (2 ** (attempt - 1)) * (4 if is_rate else 1)
            logger.warning(
                "LLM call failed (attempt %d/%d): %s. Retrying in %.0fs...",
                attempt, max_attempts, exc, delay,
            )
            time.sleep(delay)
    raise RuntimeError("retry loop exited without return or raise")  # pragma: no cover


def _call_llm(prompt: str, llm_conf: dict[str, Any], *, system: str | None = None) -> str:
    """Send a prompt to the configured LLM and return the response text.

    Supported providers: "anthropic", "openai".
    To switch provider, update llm.provider in config/content.yaml.
    """
    provider = llm_conf.get("provider", "anthropic")

    if provider == "anthropic":
        return _call_anthropic(prompt, llm_conf, system=system)

    if provider == "openai":
        return _call_openai(prompt, llm_conf, system=system)

    raise ValueError(
        f"Unknown LLM provider '{provider}'. "
        "Supported: 'anthropic', 'openai'. Update config/content.yaml."
    )


def _call_anthropic(
    prompt: str, llm_conf: dict[str, Any], *, system: str | None = None
) -> str:
    """Call the Anthropic Messages API with automatic retry on transient failures.

    Required env var: ANTHROPIC_API_KEY
    Retry count is controlled by llm.max_retries in config/content.yaml (default: 3).
    """
    max_attempts = llm_conf.get("max_retries", 3)

    def _attempt() -> str:
        import anthropic  # lazy import so the package is optional during tests

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY is not set. "
                "Get a key at https://console.anthropic.com/ and export it."
            )

        client = anthropic.Anthropic(api_key=api_key)
        kwargs: dict[str, Any] = {
            "model": llm_conf.get("model_id", "claude-haiku-4-5-20251001"),
            "max_tokens": llm_conf.get("max_tokens", 1024),
            "temperature": llm_conf.get("temperature", 0.8),
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            # Pass the system prompt as a cached content block. The Anthropic API
            # reuses the cached prefix across calls within the same 5-minute TTL,
            # saving ~90% of system-prompt token costs when the daily job processes
            # multiple stores or reviews with the same role/instruction text.
            kwargs["system"] = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ]
        try:
            message = client.messages.create(**kwargs)
        except anthropic.RateLimitError as exc:
            raise RuntimeError("Anthropic API rate limit reached. Retry later.") from exc
        except anthropic.APIError as exc:
            raise RuntimeError(f"Anthropic API error: {exc}") from exc
        if not message.content:
            raise RuntimeError("Anthropic returned an empty content list")
        return message.content[0].text

    return _call_with_retry(_attempt, max_attempts)


def _call_openai(
    prompt: str, llm_conf: dict[str, Any], *, system: str | None = None
) -> str:
    """Call the OpenAI Chat Completions API with automatic retry on transient failures.

    Required env var: OPENAI_API_KEY
    To use: set llm.provider = "openai" and llm.model_id = "gpt-4o-mini" (or similar)
    in config/content.yaml, and pip install openai.
    Retry count is controlled by llm.max_retries in config/content.yaml (default: 3).

    Ref: https://platform.openai.com/docs/api-reference/chat/create
    """
    max_attempts = llm_conf.get("max_retries", 3)

    def _attempt() -> str:
        import openai  # lazy import; install separately: pip install openai

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "OPENAI_API_KEY is not set. "
                "Get a key at https://platform.openai.com/api-keys and export it."
            )

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        client = openai.OpenAI(api_key=api_key)
        try:
            response = client.chat.completions.create(
                model=llm_conf.get("model_id", "gpt-4o-mini"),
                max_tokens=llm_conf.get("max_tokens", 1024),
                temperature=llm_conf.get("temperature", 0.8),
                messages=messages,
            )
        except openai.RateLimitError as exc:
            raise RuntimeError("OpenAI API rate limit reached. Retry later.") from exc
        except openai.APIError as exc:
            raise RuntimeError(f"OpenAI API error: {exc}") from exc
        if not response.choices:
            raise RuntimeError("OpenAI returned an empty choices list")
        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError(
                "OpenAI returned no text content "
                "(finish_reason may be 'tool_calls' — check model and prompt)"
            )
        return content

    return _call_with_retry(_attempt, max_attempts)

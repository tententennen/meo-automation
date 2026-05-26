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
from typing import Any

from . import config as cfg

logger = logging.getLogger(__name__)


def generate_post(store: dict[str, Any]) -> str:
    """Generate a Japanese 最新情報 post body for the given store.

    Args:
        store: A store dict from config.store_list() — must have 'name',
               'industry', and 'key' fields.

    Returns:
        Post body string (Japanese, within max_post_chars from content.yaml).
    """
    conf = cfg.content()
    industry = store.get("industry", "beauty_salon")
    tone_profile = conf["industry_tones"].get(industry, conf["industry_tones"]["beauty_salon"])
    banned = ", ".join(conf.get("banned_words", []))
    max_chars = conf["defaults"]["max_post_chars"]

    system = (
        f"あなたはGoogleビジネスプロフィールの投稿文を書くプロのコピーライターです。"
        f"店舗のブランドイメージを大切にし、読者に自然に響く日本語の投稿文を生成します。"
        f"指示がない限り、説明文や前置き、マークダウンは一切含めず、投稿文のみを出力してください。"
    )
    user = (
        f"店舗名: {store['name']}\n"
        f"トーン: {tone_profile['tone']}\n"
        f"テーマ候補: {', '.join(tone_profile['themes'])}\n"
        f"禁止ワード: {banned}\n"
        f"条件:\n"
        f"- 日本語で書く\n"
        f"- {max_chars}文字以内\n"
        f"- ハッシュタグは不要\n"
        f"- お客様への呼びかけを含める\n"
        f"- テーマ候補から1つ選び、自然な投稿文を1つだけ出力する\n"
        f"投稿文のみを出力してください（説明文不要）。"
    )

    text = _call_llm(user, conf["llm"], system=system)
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars]
    return text


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
    banned = ", ".join(conf.get("banned_words", []))
    max_chars = conf["defaults"]["max_reply_chars"]

    reviewer_name = review.get("reviewer", {}).get("displayName", "お客様")
    star_rating = review.get("starRating", "FIVE")
    comment = review.get("comment", "")

    system = (
        f"あなたは{store['name']}のオーナーとして、Googleレビューへ誠実かつ丁寧に返信するオーナーです。"
        f"ブランドのトーン（{tone_profile['tone']}）を守り、日本語で自然な返信を行います。"
        f"返信文のみを出力し、説明文や前置きは一切含めないでください。"
    )
    user = (
        f"禁止ワード: {banned}\n"
        f"レビュアー名: {reviewer_name}\n"
        f"評価: {star_rating}\n"
        f"レビュー内容: {comment}\n"
        f"条件:\n"
        f"- 日本語で書く\n"
        f"- {max_chars}文字以内\n"
        f"- 感謝の気持ちを伝える\n"
        f"- 低評価の場合は誠実にお詫びし、改善への意欲を示す\n"
        f"- 高評価の場合は喜びを表現し、また来てほしいと伝える\n"
        f"返信文のみを出力してください（説明文不要）。"
    )

    text = _call_llm(user, conf["llm"], system=system)
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars]
    return text


# ---------------------------------------------------------------------------
# LLM abstraction — swap provider here
# ---------------------------------------------------------------------------

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
    """Call the Anthropic Messages API.

    Required env var: ANTHROPIC_API_KEY
    """
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
        kwargs["system"] = system
    try:
        message = client.messages.create(**kwargs)
    except anthropic.RateLimitError as exc:
        raise RuntimeError("Anthropic API rate limit reached. Retry later.") from exc
    except anthropic.APIError as exc:
        raise RuntimeError(f"Anthropic API error: {exc}") from exc
    return message.content[0].text


def _call_openai(
    prompt: str, llm_conf: dict[str, Any], *, system: str | None = None
) -> str:
    """Call the OpenAI Chat Completions API.

    Required env var: OPENAI_API_KEY
    To use: set llm.provider = "openai" and llm.model_id = "gpt-4o-mini" (or similar)
    in config/content.yaml, and pip install openai.

    Ref: https://platform.openai.com/docs/api-reference/chat/create
    """
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
    return response.choices[0].message.content

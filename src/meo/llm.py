"""LLM call abstraction — swap provider without touching content generators.

To switch provider: update llm.provider in config/content.yaml.
Supported providers: "anthropic" (default), "openai".

Required environment variables (provider-dependent):
  ANTHROPIC_API_KEY  — https://console.anthropic.com/
  OPENAI_API_KEY     — https://platform.openai.com/api-keys
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)


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

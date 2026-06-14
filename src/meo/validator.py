"""Config and environment validation — runs at startup before any API call.

Calling validate_all() at the top of main() ensures every misconfiguration
is surfaced upfront (as a clear list of errors) rather than discovered
mid-run when the first API call fails.
"""

from __future__ import annotations

import os
from typing import Any

from . import config as cfg

_SUPPORTED_INDUSTRIES = {"beauty_salon", "fitness_studio"}
_SUPPORTED_PROVIDERS = {"anthropic", "openai"}
_SUPPORTED_CTA_TYPES = {"BOOK", "ORDER", "SHOP", "LEARN_MORE", "SIGN_UP", "CALL", "GET_OFFER"}

# Keys that a store entry is allowed to override from content.yaml defaults.
# Any other key in stores.yaml[store].overrides is rejected at startup.
_ALLOWED_OVERRIDE_KEYS = frozenset({
    "post_cadence_days",
    "max_post_chars",
    "max_reply_chars",
    "max_replies_per_run",
    "min_star_autoreply",
    "max_review_age_days",
})


def validate_env(content_conf: dict[str, Any] | None = None) -> list[str]:
    """Check that all required environment variables are set.

    The LLM API key checked depends on the provider configured in content.yaml:
    defaults to ANTHROPIC_API_KEY; checks OPENAI_API_KEY when provider=openai.
    """
    errors: list[str] = []
    for var in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"):
        if not os.environ.get(var):
            errors.append(f"Missing required env var: {var}")

    provider = "anthropic"
    if content_conf:
        provider = content_conf.get("llm", {}).get("provider", "anthropic")

    if provider == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            errors.append(
                "Missing required env var: OPENAI_API_KEY "
                "(required when llm.provider=openai in config/content.yaml)"
            )
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            errors.append(
                "Missing required env var: ANTHROPIC_API_KEY. "
                "Get a key at https://console.anthropic.com/"
            )
    return errors


def validate_stores(stores_data: dict[str, Any]) -> list[str]:
    """Validate the structure and values of the stores config dict."""
    errors: list[str] = []
    required_fields = ("name", "location_id", "drive_folder_id", "industry")

    for key, store in stores_data.items():
        for field in required_fields:
            if field not in store:
                errors.append(
                    f"stores.yaml: [{key}] missing required field: {field}"
                )

        industry = store.get("industry")
        if industry and industry not in _SUPPORTED_INDUSTRIES:
            errors.append(
                f"stores.yaml: [{key}] unknown industry '{industry}'. "
                f"Supported: {sorted(_SUPPORTED_INDUSTRIES)}"
            )

        overrides = store.get("overrides")
        if overrides is not None:
            unknown = set(overrides.keys()) - _ALLOWED_OVERRIDE_KEYS
            if unknown:
                errors.append(
                    f"stores.yaml: [{key}].overrides contains unknown key(s): "
                    f"{sorted(unknown)}. Allowed: {sorted(_ALLOWED_OVERRIDE_KEYS)}"
                )

        cta = store.get("call_to_action")
        if cta is not None:
            action_type = cta.get("action_type")
            if not action_type:
                errors.append(
                    f"stores.yaml: [{key}].call_to_action missing required field: action_type"
                )
            elif action_type not in _SUPPORTED_CTA_TYPES:
                errors.append(
                    f"stores.yaml: [{key}].call_to_action.action_type '{action_type}' is invalid. "
                    f"Supported: {sorted(_SUPPORTED_CTA_TYPES)}"
                )
            if "url" not in cta:
                errors.append(
                    f"stores.yaml: [{key}].call_to_action missing required field: url"
                )

    return errors


def validate_content(content_data: dict[str, Any]) -> list[str]:
    """Validate the structure and values of the content config dict."""
    errors: list[str] = []

    defaults = content_data.get("defaults")
    if not isinstance(defaults, dict):
        errors.append("content.yaml: missing required section 'defaults'")
    else:
        for field in ("language", "post_cadence_days", "max_post_chars", "max_reply_chars"):
            if field not in defaults:
                errors.append(f"content.yaml: defaults.{field} is missing")

    llm = content_data.get("llm")
    if not isinstance(llm, dict):
        errors.append("content.yaml: missing required section 'llm'")
    else:
        provider = llm.get("provider")
        if not provider:
            errors.append("content.yaml: llm.provider is missing")
        elif provider not in _SUPPORTED_PROVIDERS:
            errors.append(
                f"content.yaml: llm.provider '{provider}' is not supported. "
                f"Supported: {sorted(_SUPPORTED_PROVIDERS)}"
            )
        if not llm.get("model_id"):
            errors.append("content.yaml: llm.model_id is missing")

    if not isinstance(content_data.get("industry_tones"), dict):
        errors.append("content.yaml: missing required section 'industry_tones'")

    return errors


def validate_all(*, check_env: bool = True) -> list[str]:
    """Run all validation checks and return a list of error strings.

    An empty list means the configuration is valid and a live run can proceed.

    Args:
        check_env: Whether to check environment variables (default True).
                   Set to False in CI jobs that only validate config structure.
    """
    errors: list[str] = []

    content_conf: dict[str, Any] | None = None
    try:
        content_conf = cfg.content()
        errors.extend(validate_content(content_conf))
    except Exception as exc:
        errors.append(f"content.yaml: failed to load: {exc}")

    try:
        errors.extend(validate_stores(cfg.stores()))
    except Exception as exc:
        errors.append(f"stores.yaml: failed to load: {exc}")

    if check_env:
        errors.extend(validate_env(content_conf))

    return errors

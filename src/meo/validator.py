"""Config and environment validation — runs at startup before any API call.

Calling validate_all() at the top of main() ensures every misconfiguration
is surfaced upfront (as a clear list of errors) rather than discovered
mid-run when the first API call fails.
"""

from __future__ import annotations

import os
import re
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
    "recent_post_context_count",
    "recent_reply_context_count",
    "post_time_window_jst",
    "max_drive_image_bytes",
    "max_banned_retries",
    "holiday_context_days",
    "max_post_similarity",
    "max_reply_similarity",
    "max_similarity_retries",
})

_TIME_WINDOW_PATTERN = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")


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
            # An empty string url silently disables the CTA button in posts.py
            # without any warning — detect it here so the operator gets a clear error.
            if not cta.get("url"):
                errors.append(
                    f"stores.yaml: [{key}].call_to_action.url is missing or empty"
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
        max_retries = llm.get("max_retries")
        if max_retries is not None and (
            not isinstance(max_retries, int) or max_retries < 1
        ):
            errors.append(
                "content.yaml: llm.max_retries must be an integer >= 1 "
                "(omit to use the default of 3)"
            )

    if not isinstance(content_data.get("industry_tones"), dict):
        errors.append("content.yaml: missing required section 'industry_tones'")

    banned_words = content_data.get("banned_words")
    if banned_words is not None and not isinstance(banned_words, list):
        errors.append(
            f"content.yaml: banned_words must be a YAML list (e.g. - \"激安\"), "
            f"got {type(banned_words).__name__}. "
            "A bare string would be iterated character-by-character in LLM prompts."
        )

    if isinstance(defaults, dict):
        recent_count = defaults.get("recent_post_context_count")
        if recent_count is not None and (
            not isinstance(recent_count, int) or recent_count < 0
        ):
            errors.append(
                "content.yaml: defaults.recent_post_context_count must be an integer >= 0 "
                "(omit to use the default of 3; set to 0 to disable recent-post context)"
            )

        recent_reply_count = defaults.get("recent_reply_context_count")
        if recent_reply_count is not None and (
            not isinstance(recent_reply_count, int) or recent_reply_count < 0
        ):
            errors.append(
                "content.yaml: defaults.recent_reply_context_count must be an integer >= 0 "
                "(omit to use the default of 3; set to 0 to disable recent-reply context)"
            )

        window = defaults.get("post_time_window_jst")
        if window is not None:
            if not isinstance(window, str):
                errors.append(
                    "content.yaml: defaults.post_time_window_jst must be a string "
                    "in 'HH:MM-HH:MM' format (e.g. '06:00-23:00')"
                )
            else:
                m = _TIME_WINDOW_PATTERN.match(window)
                if not m:
                    errors.append(
                        f"content.yaml: defaults.post_time_window_jst {window!r} must match "
                        "'HH:MM-HH:MM' format (e.g. '06:00-23:00')"
                    )
                else:
                    sh, sm, eh, em = (int(x) for x in m.groups())
                    if not (0 <= sh <= 23 and 0 <= sm <= 59 and 0 <= eh <= 23 and 0 <= em <= 59):
                        errors.append(
                            f"content.yaml: defaults.post_time_window_jst {window!r} contains "
                            "out-of-range hour or minute values"
                        )

        max_image_bytes = defaults.get("max_drive_image_bytes")
        if max_image_bytes is not None and (
            not isinstance(max_image_bytes, int) or max_image_bytes < 1
        ):
            errors.append(
                "content.yaml: defaults.max_drive_image_bytes must be a positive integer "
                "(default: 5242880 = 5 MB, the GBP upload limit)"
            )

        max_banned_retries = defaults.get("max_banned_retries")
        if max_banned_retries is not None and (
            not isinstance(max_banned_retries, int) or max_banned_retries < 0
        ):
            errors.append(
                "content.yaml: defaults.max_banned_retries must be an integer >= 0 "
                "(0 = log warning only, no retry; default: 2)"
            )

        holiday_context_days = defaults.get("holiday_context_days")
        if holiday_context_days is not None and (
            not isinstance(holiday_context_days, int) or holiday_context_days < 0
        ):
            errors.append(
                "content.yaml: defaults.holiday_context_days must be an integer >= 0 "
                "(0 = disable holiday injection; default: 7)"
            )

        max_post_similarity = defaults.get("max_post_similarity")
        if max_post_similarity is not None and (
            not isinstance(max_post_similarity, (int, float))
            or not (0.0 <= max_post_similarity <= 1.0)
        ):
            errors.append(
                "content.yaml: defaults.max_post_similarity must be a number between "
                "0.0 and 1.0 inclusive (0.0 = always warn, 1.0 = disable; default: 0.7)"
            )

        max_reply_similarity = defaults.get("max_reply_similarity")
        if max_reply_similarity is not None and (
            not isinstance(max_reply_similarity, (int, float))
            or not (0.0 <= max_reply_similarity <= 1.0)
        ):
            errors.append(
                "content.yaml: defaults.max_reply_similarity must be a number between "
                "0.0 and 1.0 inclusive (0.0 = always warn, 1.0 = disable; default: 0.7)"
            )

        max_similarity_retries = defaults.get("max_similarity_retries")
        if max_similarity_retries is not None and (
            not isinstance(max_similarity_retries, int) or max_similarity_retries < 0
        ):
            errors.append(
                "content.yaml: defaults.max_similarity_retries must be an integer >= 0 "
                "(0 = warn only, no retry; default: 1)"
            )

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

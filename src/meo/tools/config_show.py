"""meo-config-show — display effective per-store configuration.

Merges global content.yaml defaults with per-store overrides and shows the
complete resolved settings for each store. Overrides are annotated so the
owner can immediately see which fields differ from the global default.
No Google credentials required — reads only config files.

Usage:
    meo-config-show                                   # all stores
    meo-config-show --store the_body_kyoto            # single store
    meo-config-show --store the_body_kyoto mybear_studio_kyoto
    python -m meo.tools.config_show
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from .. import config as cfg

_DIVIDER = "─" * 56

# Ordered list of content defaults to display.
_DEFAULT_FIELDS: list[tuple[str, str]] = [
    ("language", "language"),
    ("post_cadence_days", "post_cadence_days"),
    ("max_post_chars", "max_post_chars"),
    ("max_reply_chars", "max_reply_chars"),
    ("max_replies_per_run", "max_replies_per_run"),
    ("min_star_autoreply", "min_star_autoreply"),
    ("max_review_age_days", "max_review_age_days"),
    ("post_time_window_jst", "post_time_window_jst"),
    ("recent_post_context_count", "recent_post_context_count"),
    ("recent_reply_context_count", "recent_reply_context_count"),
]


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def run_config_show(store_keys: list[str] | None = None) -> list[dict[str, Any]]:
    """Return per-store effective configuration data for all (or selected) stores.

    Returns a list of dicts — one per store — with all fields needed for
    display by :func:`_format_output`. Unknown keys in ``store_keys`` are
    silently excluded (validate keys before calling).
    """
    stores = cfg.store_list()
    if store_keys:
        stores = [s for s in stores if s["key"] in store_keys]

    content_cfg = cfg.content()
    global_defaults: dict[str, Any] = dict(content_cfg.get("defaults", {}))
    industry_tones: dict[str, Any] = content_cfg.get("industry_tones", {})
    llm_cfg: dict[str, Any] = content_cfg.get("llm", {})
    banned_words: list[str] = content_cfg.get("banned_words", [])

    results: list[dict[str, Any]] = []
    for store in stores:
        key = store["key"]
        location_id: str = store.get("location_id", "")
        drive_folder_id: str = store.get("drive_folder_id", "")
        industry: str = store.get("industry", "")
        overrides: dict[str, Any] = dict(store.get("overrides") or {})
        cta: dict[str, Any] | None = store.get("call_to_action")

        effective = cfg.effective_defaults(store)
        tone_profile: dict[str, Any] = dict(industry_tones.get(industry, {}))

        results.append({
            "store_key": key,
            "store_name": store["name"],
            "location_id": location_id,
            "location_id_configured": bool(location_id and "TODO" not in location_id),
            "drive_folder_id": drive_folder_id,
            "drive_folder_id_configured": bool(drive_folder_id and "TODO" not in drive_folder_id),
            "industry": industry,
            "effective_defaults": effective,
            "global_defaults": global_defaults,
            "overrides": overrides,
            "tone_profile": tone_profile,
            "call_to_action": cta,
            "llm": llm_cfg,
            "banned_words": banned_words,
        })

    return results


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _format_id_line(label: str, value: str, configured: bool) -> str:
    """Format a single ID field line (location_id or drive_folder_id)."""
    if configured:
        display = value if len(value) <= 50 else value[:47] + "..."
        return f"  ✓ {label}: {display}"
    placeholder = value if len(value) <= 60 else value[:57] + "..."
    return f"  ! {label}: [未設定] {placeholder}"


def _format_defaults_section(
    effective: dict[str, Any],
    global_defaults: dict[str, Any],
    overrides: dict[str, Any],
) -> str:
    """Format the コンテンツ設定 section, annotating overridden fields."""
    lines = ["  コンテンツ設定:"]
    for label, key in _DEFAULT_FIELDS:
        value = effective.get(key, "—")
        if key in overrides:
            global_val = global_defaults.get(key, "—")
            lines.append(f"    {label:<32} {value}  ← override (global: {global_val})")
        else:
            lines.append(f"    {label:<32} {value}")
    return "\n".join(lines)


def _format_tone_section(industry: str, tone_profile: dict[str, Any]) -> str:
    """Format the industry tone profile section."""
    if not tone_profile:
        return (
            f"  トーンプロファイル: [未設定] "
            f"industry='{industry}' がcontent.yamlに見つかりません"
        )
    tone_desc = tone_profile.get("tone", "—")
    themes = tone_profile.get("themes", [])
    themes_str = "、".join(themes) if themes else "—"
    lines = [
        f"  トーンプロファイル ({industry}):",
        f"    tone:   {tone_desc}",
        f"    テーマ: {themes_str}",
    ]
    return "\n".join(lines)


def _format_llm_section(llm: dict[str, Any]) -> str:
    """Format the LLM settings section."""
    if not llm:
        return "  LLM: [未設定]"
    lines = [
        "  LLM:",
        f"    provider:    {llm.get('provider', '—')}",
        f"    model_id:    {llm.get('model_id', '—')}",
        f"    temperature: {llm.get('temperature', '—')}",
        f"    max_tokens:  {llm.get('max_tokens', '—')}",
        f"    max_retries: {llm.get('max_retries', '—')}",
    ]
    return "\n".join(lines)


def _format_cta_section(cta: dict[str, Any] | None) -> str:
    """Format the call_to_action section."""
    if not cta:
        return "  call_to_action: [未設定]"
    action_type = cta.get("action_type", "—")
    url = cta.get("url") or "—"
    return f"  call_to_action: type={action_type}  url={url}"


def _format_banned_words(banned_words: list[str]) -> str:
    """Format the banned words line."""
    if not banned_words:
        return "  禁止ワード: なし"
    return f"  禁止ワード: {', '.join(banned_words)}"


def _format_output(results: list[dict[str, Any]]) -> str:
    """Format run_config_show() results into a human-readable string."""
    if not results:
        return "No stores found."

    sections: list[str] = ["MEO Automation — 店舗別 有効設定\n"]

    for r in results:
        sections.append(_DIVIDER)
        sections.append(f"{r['store_name']}  ({r['store_key']})")
        sections.append(_format_id_line("location_id", r["location_id"], r["location_id_configured"]))
        sections.append(_format_id_line("drive_folder_id", r["drive_folder_id"], r["drive_folder_id_configured"]))
        sections.append("")
        sections.append(_format_defaults_section(
            r["effective_defaults"], r["global_defaults"], r["overrides"]
        ))
        sections.append("")
        sections.append(_format_tone_section(r["industry"], r["tone_profile"]))
        sections.append("")
        sections.append(_format_llm_section(r["llm"]))
        sections.append("")
        sections.append(_format_banned_words(r["banned_words"]))
        sections.append(_format_cta_section(r["call_to_action"]))
        sections.append("")

    sections.append(_DIVIDER)
    sections.append(f"合計: {len(results)} 店舗")

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Display the effective (merged) configuration for each store.\n"
            "Combines global content.yaml defaults with per-store overrides.\n"
            "No Google credentials required."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--store",
        metavar="STORE_KEY",
        nargs="+",
        help=(
            "Show config for these store key(s) only. "
            "Keys: the_body_osaka_shinsaibashi, the_body_kyoto, mybear_studio_kyoto. "
            "Defaults to all stores."
        ),
    )
    args = parser.parse_args()

    stores = cfg.store_list()
    known_keys = {s["key"] for s in stores}

    if args.store:
        unknown = [k for k in args.store if k not in known_keys]
        if unknown:
            print(
                f"Unknown store key(s): {unknown}. "
                f"Valid keys: {sorted(known_keys)}",
                file=sys.stderr,
            )
            sys.exit(1)

    results = run_config_show(args.store)
    print(_format_output(results))
    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    main()

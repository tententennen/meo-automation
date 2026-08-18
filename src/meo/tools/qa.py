"""meo-qa — list and auto-answer Q&A questions on Google Business Profile.

Fetches unanswered customer questions from GBP Q&A for one or all stores,
generates AI answers using the configured LLM, and posts them as owner
answers.  Mirrors the review-reply workflow — questions answered on GBP are
skipped, and questions answered in a previous run but not yet propagated
through GBP are also skipped using the local state guard.

Usage:
    meo-qa                              # list + auto-answer all stores
    meo-qa --store the_body_kyoto       # one store only
    meo-qa --dry-run                    # preview answers without posting
    meo-qa --list-only                  # show questions, don't generate or post
    python -m meo.tools.qa
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from .. import config as cfg
from ..auth import get_credentials
from ..business_profile import BusinessProfileClient
from ..qa import _extract_question_id, _has_owner_answer, run_qa_for_store

logger = logging.getLogger(__name__)

# Number of question-text characters to show in the list view.
_QUESTION_PREVIEW_LEN = 100


def _format_question_list(
    questions: list[dict[str, Any]],
    store_name: str,
    store_key: str,
) -> str:
    """Build a human-readable listing of Q&A questions for one store."""
    total = len(questions)
    unanswered = [q for q in questions if not _has_owner_answer(q)]

    divider = "─" * 50
    lines: list[str] = [
        divider,
        f"{store_name} ({store_key})",
        f"質問数: {total}件 / 未回答: {len(unanswered)}件",
        "",
    ]

    if not questions:
        lines.append("  （質問なし）")
        lines.append("")
        return "\n".join(lines)

    for q in questions:
        qid = _extract_question_id(q)
        text = q.get("text", "（質問文なし）")
        preview = text[:_QUESTION_PREVIEW_LEN] + "…" if len(text) > _QUESTION_PREVIEW_LEN else text
        answered = _has_owner_answer(q)
        upvotes = q.get("upvoteCount", 0)
        total_answers = q.get("totalAnswerCount", 0)
        status = "✓ 回答済" if answered else "✗ 未回答"

        lines.append(f"  [{status}] {preview}")
        lines.append(f"           id={qid}  いいね={upvotes}  回答数={total_answers}")
        lines.append("")

    return "\n".join(lines)


def run_list_questions(store_keys: list[str] | None = None) -> None:
    """List Q&A questions for one or all stores (no LLM calls, no writes)."""
    stores = cfg.store_list()
    if store_keys:
        stores = [s for s in stores if s["key"] in store_keys]

    logger.info("Authenticating with Google APIs...")
    try:
        creds = get_credentials()
    except EnvironmentError as exc:
        print(f"Auth failed: {exc}", file=sys.stderr)
        sys.exit(1)

    gbp = BusinessProfileClient(creds)
    had_error = False

    for store in stores:
        store_key = store["key"]
        if "TODO" in store.get("location_id", ""):
            print(
                f"[{store_key}] location_id not configured in config/stores.yaml — skipping.",
                file=sys.stderr,
            )
            continue
        try:
            questions = gbp.list_questions(store["location_id"])
            print(_format_question_list(questions, store["name"], store_key))
        except Exception as exc:
            print(f"[{store_key}] Failed to fetch questions: {exc}", file=sys.stderr)
            had_error = True

    sys.exit(1 if had_error else 0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch unanswered Q&A questions and post AI-generated owner answers.\n"
            "Skips questions already answered on GBP or answered locally in a prior run."
        )
    )
    parser.add_argument(
        "--store",
        metavar="STORE_KEY",
        nargs="+",
        help=(
            "Run only for the given store key(s). Defaults to all stores.\n"
            "Keys: the_body_osaka_shinsaibashi, the_body_kyoto, mybear_studio_kyoto"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate answers and log them, but do not post to GBP.",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="List questions with answered/unanswered status. No LLM calls, no writes.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.store:
        known = {s["key"] for s in cfg.store_list()}
        unknown = [k for k in args.store if k not in known]
        if unknown:
            print(
                f"Unknown store key(s): {unknown}. Valid keys: {sorted(known)}",
                file=sys.stderr,
            )
            sys.exit(1)

    if args.list_only:
        run_list_questions(args.store)
        return  # exits inside

    # Full auto-answer mode
    logger.info("Authenticating with Google APIs...")
    try:
        creds = get_credentials()
    except EnvironmentError as exc:
        logger.critical("Auth failed: %s", exc)
        sys.exit(1)

    gbp = BusinessProfileClient(creds)
    stores = cfg.store_list()
    if args.store:
        stores = [s for s in stores if s["key"] in args.store]

    had_error = False

    for store in stores:
        store_key = store["key"]
        if "TODO" in store.get("location_id", ""):
            logger.error(
                "[%s] location_id not configured in config/stores.yaml — skipping.",
                store_key,
            )
            had_error = True
            continue
        try:
            result = run_qa_for_store(store, gbp, dry_run=args.dry_run)
            mode = "DRY RUN — " if args.dry_run else ""
            logger.info(
                "[%s] %sAnswered: %d, Already answered on GBP: %d, Deferred: %d, Errors: %d",
                store_key,
                mode,
                result["answered"],
                result["skipped"],
                result["deferred"],
                len(result["errors"]),
            )
            if result["errors"]:
                had_error = True
        except Exception as exc:
            logger.error("[%s] Q&A run failed: %s", store_key, exc, exc_info=True)
            had_error = True

    sys.exit(1 if had_error else 0)


if __name__ == "__main__":  # pragma: no cover
    main()

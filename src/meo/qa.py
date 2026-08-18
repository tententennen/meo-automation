"""Fetch unanswered Q&A questions and post AI-generated owner answers, per store."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from . import config as cfg
from .business_profile import BusinessProfileClient
from .content import generate_answer
from .state import (
    get_answered_questions,
    record_answer_content,
    record_answered_question,
)

logger = logging.getLogger(__name__)


def run_qa_for_store(
    store: dict[str, Any],
    gbp: BusinessProfileClient,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Fetch unanswered Q&A questions for a store and post AI-generated answers.

    Args:
        store:   Store dict from config.store_list().
        gbp:     Authenticated BusinessProfileClient.
        dry_run: If True, log what would happen but post no answers.

    Returns:
        A result dict with keys: store_key, answered (count), skipped (count),
        deferred (count), errors (list[str]).
    """
    store_key = store["key"]
    location_id = store["location_id"]
    store_defaults = cfg.effective_defaults(store)

    logger.info("[%s] Fetching Q&A questions...", store_key)
    questions = gbp.list_questions(location_id)
    unanswered = [q for q in questions if not _has_owner_answer(q)]
    already_answered_count = len(questions) - len(unanswered)

    # Skip questions answered locally — guards against GBP propagation lag.
    # An answer POSTed in a previous run may not yet appear in list_questions(),
    # making those questions look unanswered. Checking our local set prevents
    # double-answering within the same propagation window.
    locally_answered = set(get_answered_questions(store_key))
    if locally_answered:
        before_local = len(unanswered)
        unanswered = [
            q for q in unanswered if _extract_question_id(q) not in locally_answered
        ]
        local_skip = before_local - len(unanswered)
        if local_skip:
            logger.info(
                "[%s] %d question(s) skipped (answered locally, awaiting GBP propagation).",
                store_key,
                local_skip,
            )

    # Age filter — skip very old questions to prevent mass-answering on first run.
    # Default 180 days is more generous than reviews (90 days) because Q&A
    # questions tend to remain relevant longer and accumulate slowly.
    max_age_days: int = store_defaults.get("max_question_age_days", 180)
    if max_age_days > 0:
        fresh: list[dict[str, Any]] = []
        too_old: list[dict[str, Any]] = []
        for q in unanswered:
            age = _question_age_days(q)
            if age is not None and age > max_age_days:
                too_old.append(q)
            else:
                fresh.append(q)
        if too_old:
            logger.info(
                "[%s] %d question(s) skipped (older than max_question_age_days=%d).",
                store_key,
                len(too_old),
                max_age_days,
            )
        unanswered = fresh

    unanswered_total = len(unanswered)
    logger.info(
        "[%s] %d unanswered question(s) of %d total.",
        store_key,
        unanswered_total,
        len(questions),
    )

    max_qa: int = store_defaults.get("max_qa_per_run", 10)
    if unanswered_total > max_qa:
        logger.warning(
            "[%s] %d unanswered questions found; capping at %d (max_qa_per_run). "
            "Remaining will be picked up in future runs.",
            store_key,
            unanswered_total,
            max_qa,
        )
        unanswered = unanswered[:max_qa]

    answered = 0
    errors: list[str] = []

    for question in unanswered:
        question_id = _extract_question_id(question)
        question_name = question.get("name", "")
        question_text = question.get("text", "")
        author = question.get("author", {}).get("displayName", "お客様")

        logger.info(
            "[%s] Generating answer for question by %s (id=%s): %s…",
            store_key,
            author,
            question_id,
            question_text[:60],
        )

        try:
            answer_text = generate_answer(question_text, store)
            logger.info(
                "[%s] Answer (%d chars): %s",
                store_key,
                len(answer_text),
                answer_text[:80],
            )

            if dry_run:
                logger.info(
                    "[%s] DRY RUN — would answer question %s:\n%s",
                    store_key,
                    question_id,
                    answer_text,
                )
            else:
                gbp.upsert_answer(question_name, answer_text)
                record_answered_question(store_key, question_id)
                record_answer_content(store_key, question_id, question_text, answer_text)
            answered += 1
        except Exception as exc:
            msg = f"Failed to answer question {question_id}: {exc}"
            logger.error("[%s] %s", store_key, msg)
            errors.append(msg)

    return {
        "store_key": store_key,
        "answered": answered,
        "skipped": already_answered_count,
        "deferred": unanswered_total - len(unanswered),
        "errors": errors,
    }


def _has_owner_answer(question: dict[str, Any]) -> bool:
    """Return True if the business owner has already answered this question.

    Owner answers have author.type == "MERCHANT" in the topAnswers list.
    A question with totalAnswerCount == 0 is definitively unanswered.
    """
    if question.get("totalAnswerCount", 0) == 0:
        return False
    for answer in question.get("topAnswers", []):
        if answer.get("author", {}).get("type", "").upper() == "MERCHANT":
            return True
    return False


def _extract_question_id(question: dict[str, Any]) -> str:
    """Extract the bare question ID from the full resource name.

    Resource name format: 'locations/{locationId}/questions/{questionId}'
    """
    name = question.get("name", "")
    return name.split("/")[-1]


def _question_age_days(question: dict[str, Any]) -> float | None:
    """Return the age of a question in fractional days, or None if undetermined.

    Parses the GBP Q&A API's RFC 3339 createTime field.  Returns None for
    missing or unparseable timestamps — callers treat None as "include this
    question" so we never silently drop questions we can't date.
    """
    ts = question.get("createTime")
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (datetime.now(tz=timezone.utc) - dt).total_seconds() / 86400
    except (ValueError, TypeError):
        return None

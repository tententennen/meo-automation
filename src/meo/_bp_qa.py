"""Mixin: Q&A (Questions & Answers) methods for BusinessProfileClient.

Internal module — not part of the public meo API.

Ref: https://developers.google.com/my-business/reference/qanda/rest/v1/locations.questions
"""

from __future__ import annotations

import logging
from typing import Any

from ._bp_constants import _QA_BASE, _qa_location_name, _raise_for_status

logger = logging.getLogger(__name__)


class _QaMixin:
    """Provides list_questions() and upsert_answer() to BusinessProfileClient."""

    def list_questions(
        self,
        location_id: str,
        *,
        page_size: int = 20,
        answers_per_question: int = 5,
    ) -> list[dict[str, Any]]:
        """Fetch all Q&A questions for a location, paginating automatically.

        Returns a flat list of question dicts, each including the topAnswers
        sub-list so callers can detect whether the owner has already replied.

        Args:
            location_id:          Full location resource name, e.g.
                                  'accounts/{a}/locations/{l}'.
            page_size:            Max questions per API page (API max: 100).
            answers_per_question: Top answers to include per question (max: 10).

        Ref: https://developers.google.com/my-business/reference/qanda/rest/v1/locations.questions/list
        """
        qa_parent = _qa_location_name(location_id)
        url = f"{_QA_BASE}/{qa_parent}/questions"
        params: dict[str, Any] = {
            "pageSize": page_size,
            "answersPerQuestion": answers_per_question,
        }
        questions: list[dict[str, Any]] = []

        while True:
            resp = self._session.get(url, params=params)  # type: ignore[attr-defined]
            _raise_for_status(resp)
            data = resp.json()
            questions.extend(data.get("questions", []))
            next_token = data.get("nextPageToken")
            if not next_token:
                break
            params["pageToken"] = next_token

        logger.info("Fetched %d Q&A questions for %s.", len(questions), location_id)
        return questions

    def upsert_answer(self, question_name: str, answer_text: str) -> dict[str, Any]:
        """Post or update the owner's answer to a Q&A question.

        Creates a new answer if none exists; replaces the owner's existing
        answer if one was already posted.

        Args:
            question_name: Full question resource name.
                           Format: 'locations/{locationId}/questions/{questionId}'
            answer_text:   The answer text to post.

        Returns:
            The Answer resource dict returned by the API.

        Ref: https://developers.google.com/my-business/reference/qanda/rest/v1/locations.questions.answers/upsert
        """
        url = f"{_QA_BASE}/{question_name}:upsertAnswer"
        body = {"answer": {"text": answer_text}}
        resp = self._session.post(url, json=body)  # type: ignore[attr-defined]
        _raise_for_status(resp)
        result = resp.json()
        logger.info("Posted answer for question %s.", question_name)
        return result

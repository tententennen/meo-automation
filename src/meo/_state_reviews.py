"""Replied-review and held-review tracking for state.py.

Internal module — all public functions are re-exported by state.py.
"""

from __future__ import annotations

import logging
from typing import Any

from ._state_io import _clear_section, _load, _record_rotation, _save


def _today():
    import meo.state as _state_mod
    return _state_mod._today()

logger = logging.getLogger(__name__)

def record_replied_review(store_key: str, review_id: str) -> None:
    """Record that a reply was successfully posted for review_id.

    A reply posted via the GBP API can take several minutes to appear in
    list_reviews(). If a second run fires before propagation completes, the
    review still looks unreplied and the runner would try to reply again.
    We track replied IDs locally so the second run skips them.
    """
    import meo.state as _state_mod
    _record_rotation("replied_reviews", store_key, review_id, _state_mod._REPLIED_REVIEW_CAPACITY)
    logger.debug("Recorded replied review for %s: %s", store_key, review_id)


def get_replied_reviews(store_key: str) -> list[str]:
    """Return review IDs replied to locally for store_key (most recent first)."""
    return list(_load().get("replied_reviews", {}).get(store_key, []))


def record_held_reviews(
    store_key: str,
    reviews: list[dict[str, Any]],
) -> None:
    """Snapshot reviews currently held for manual reply for store_key.

    Each entry in ``reviews`` must be a dict with keys:
        review_id, reviewer, stars, comment

    The snapshot REPLACES the previous one — entries do not accumulate across
    runs.  Call with an empty list when all held reviews have been resolved so
    ``get_held_reviews()`` returns [] for the next run.
    """
    today = _today().isoformat()
    snapshot = [{**r, "date": today} for r in reviews]
    state = _load()
    state.setdefault("held_reviews", {})[store_key] = snapshot
    _save(state)
    logger.debug("Snapshotted %d held review(s) for %s.", len(snapshot), store_key)


def get_held_reviews(store_key: str) -> list[dict[str, Any]]:
    """Return the held-review snapshot for store_key from the last run."""
    return list(_load().get("held_reviews", {}).get(store_key, []))


def clear_replied_reviews(store_key: str | None = None) -> list[str]:
    """Clear the local replied-review tracking set for one or all stores.

    Safe to clear — GBP's own reviewReply field remains the authoritative source.

    Returns:
        List of store keys whose tracking set was cleared.
    """
    cleared = _clear_section("replied_reviews", store_key)
    logger.debug("Cleared replied reviews for: %s", cleared or "none")
    return cleared


def clear_held_reviews(store_key: str | None = None) -> list[str]:
    """Clear the held-review snapshot for one or all stores.

    Returns:
        List of store keys whose snapshot was cleared.
    """
    cleared = _clear_section("held_reviews", store_key)
    logger.debug("Cleared held reviews for: %s", cleared or "none")
    return cleared


def dismiss_held_review(store_key: str, review_id: str) -> None:
    """Permanently dismiss a review so the runner never queues it for manual reply.

    Also removes the review from the current held snapshot immediately so
    get_held_reviews() and meo-export held-reviews reflect the change
    without waiting for the next daily run.
    """
    state = _load()
    dismissed = state.setdefault("dismissed_reviews", {})
    ids: list[str] = dismissed.get(store_key, [])
    if review_id not in ids:
        ids.append(review_id)
    dismissed[store_key] = ids
    held: dict[str, list] = state.get("held_reviews", {})
    if store_key in held:
        held[store_key] = [r for r in held[store_key] if r.get("review_id") != review_id]
    state["held_reviews"] = held
    _save(state)
    logger.debug("Dismissed review %s for %s.", review_id, store_key)


def get_dismissed_reviews(store_key: str) -> list[str]:
    """Return the list of permanently dismissed review IDs for store_key."""
    return list(_load().get("dismissed_reviews", {}).get(store_key, []))


def undismiss_held_review(store_key: str, review_id: str) -> bool:
    """Remove a review ID from the dismissed set; returns True if it was found.

    After undismissing, the review will reappear in the held queue on the
    next daily run if it is still below min_star_autoreply.
    """
    state = _load()
    dismissed = state.get("dismissed_reviews", {})
    ids: list[str] = dismissed.get(store_key, [])
    if review_id not in ids:
        return False
    ids.remove(review_id)
    dismissed[store_key] = ids
    state["dismissed_reviews"] = dismissed
    _save(state)
    logger.debug("Undismissed review %s for %s.", review_id, store_key)
    return True

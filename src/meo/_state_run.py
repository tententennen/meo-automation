"""Run-result streak tracking for state.py.

Internal module — all public functions are re-exported by state.py.
"""

from __future__ import annotations

import logging

from ._state_io import _load, _save


def _today():
    import meo.state as _state_mod
    return _state_mod._today()

logger = logging.getLogger(__name__)


def record_run_result(store_key: str, success: bool, error_type: str | None = None) -> None:
    """Record the outcome of a live daily run for store_key.

    On success: resets consecutive_failures to 0, increments consecutive_successes;
    clears last_error_type and last_error_date.
    On failure: increments consecutive_failures, resets consecutive_successes to 0;
    records error_type and today's date.

    Only call for live runs — dry-run results must not affect the streak so that
    test/preview runs do not mask real failures.
    """
    today = _today().isoformat()
    state = _load()
    results: dict = state.setdefault("run_results", {})
    entry: dict = dict(results.get(store_key, {}))
    if success:
        entry["consecutive_failures"] = 0
        entry["consecutive_successes"] = entry.get("consecutive_successes", 0) + 1
        entry["last_error_type"] = None
        entry["last_error_date"] = None
    else:
        entry["consecutive_failures"] = entry.get("consecutive_failures", 0) + 1
        entry["consecutive_successes"] = 0
        entry["last_error_type"] = error_type
        entry["last_error_date"] = today
    results[store_key] = entry
    state["run_results"] = results
    _save(state)
    logger.debug("Recorded run result for %s: success=%s", store_key, success)


def get_run_streak(store_key: str) -> dict:
    """Return the run streak data for store_key.

    Always returns a dict with keys:
      consecutive_failures (int), consecutive_successes (int),
      last_error_type (str | None), last_error_date (str | None).
    Never raises — returns zero-defaults when no data exists for the store.
    """
    defaults: dict = {
        "consecutive_failures": 0,
        "consecutive_successes": 0,
        "last_error_type": None,
        "last_error_date": None,
    }
    stored = _load().get("run_results", {}).get(store_key, {})
    return {**defaults, **stored}

"""Regression tests for module-level path constants.

main._LOG_DIR, state._STATE_FILE, and status._STATE_FILE each compute the repo
root by walking up __file__ with parents[N].  An off-by-one in N silently places
log files and state.json *outside* the repository, breaking:
  - state persistence across runs (cadence guard, rotation history)
  - the GitHub Actions `logs/meo.log` artifact upload
  - the GitHub Actions `logs/state.json` cache save/restore

These tests use config._ROOT (parents[2] for src/meo/config.py — verified correct
by the comment in config.py itself) as the ground-truth project root, then assert
that all three constants resolve to the same root.
"""

from pathlib import Path

import meo.config as cfg_mod
import meo.main as main_mod
import meo.state as state_mod
from meo.tools import status as status_mod


def _project_root() -> Path:
    """Derive the repo root using config.py's known-correct parents[2] index."""
    return Path(cfg_mod.__file__).resolve().parents[2]


def test_state_file_resolves_inside_project():
    """state._STATE_FILE must be the project root's logs/state.json."""
    root = _project_root()
    assert state_mod._STATE_FILE == root / "logs" / "state.json", (
        f"state._STATE_FILE={state_mod._STATE_FILE!r} does not point inside the project. "
        "An off-by-one in parents[] silently breaks state persistence across runs."
    )


def test_log_dir_resolves_inside_project():
    """main._LOG_DIR must be the project root's logs/ directory."""
    root = _project_root()
    assert main_mod._LOG_DIR == root / "logs", (
        f"main._LOG_DIR={main_mod._LOG_DIR!r} does not point inside the project. "
        "An off-by-one in parents[] silently writes log files outside the repo."
    )


def test_status_state_file_resolves_inside_project():
    """status._STATE_FILE must be the project root's logs/state.json."""
    root = _project_root()
    assert status_mod._STATE_FILE == root / "logs" / "state.json", (
        f"status._STATE_FILE={status_mod._STATE_FILE!r} does not point inside the project. "
        "An off-by-one in parents[] silently reads state from the wrong location."
    )

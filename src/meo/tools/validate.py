"""CLI: validate config files and environment variables before a live run.

Usage:
    meo-validate              # or: python -m meo.tools.validate

Exits 0 if all checks pass, exits 1 and prints errors if any check fails.
Useful as a pre-flight step before the first live run or after editing config.
"""

from __future__ import annotations

import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from ..validator import validate_all


def main() -> None:
    errors = validate_all()
    if errors:
        print(f"Config validation FAILED — {len(errors)} error(s):")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    print("Config validation OK — all checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()

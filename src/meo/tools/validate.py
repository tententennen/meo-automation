"""CLI: validate config files and environment variables before a live run.

Usage:
    meo-validate              # check config + env vars (requires credentials)
    meo-validate --no-env     # check only config structure (safe in CI without credentials)

Exits 0 if all checks pass, exits 1 and prints errors if any check fails.
Useful as a pre-flight step before the first live run or after editing config.
"""

from __future__ import annotations

import argparse
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from ..validator import validate_all


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate MEO config files and environment variables.",
    )
    parser.add_argument(
        "--no-env",
        action="store_true",
        help=(
            "Skip environment variable checks. "
            "Use in CI where credentials are not present but config structure should be valid."
        ),
    )
    args = parser.parse_args()

    errors = validate_all(check_env=not args.no_env)
    if errors:
        print(f"Config validation FAILED — {len(errors)} error(s):")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    scope = "config structure" if args.no_env else "config + environment"
    print(f"Config validation OK — {scope} checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()

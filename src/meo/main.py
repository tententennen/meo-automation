"""Single unattended entrypoint — runs all 3 stores end-to-end.

Usage:
    python -m meo.main              # live run
    python -m meo.main --dry-run    # log what would happen, no API writes

Per-store error isolation: one store failing does not block others.
All results (and errors) are logged; the process exits with code 1 if
any store encountered an error.

Required environment variables — see README.md § Environment Variables:
    GOOGLE_CLIENT_ID
    GOOGLE_CLIENT_SECRET
    GOOGLE_REFRESH_TOKEN
    ANTHROPIC_API_KEY
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any

# Optional: load .env in development environments only.
# In production, env vars should already be set by the scheduler/CI system.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from . import config as cfg
from .auth import get_credentials
from .business_profile import BusinessProfileClient
from .drive import DriveClient
from .notify import send_run_summary
from .posts import run_post_for_store
from .reviews import run_reviews_for_store
from .validator import validate_all

_LOG_DIR = Path(__file__).resolve().parents[3] / "logs"


def _setup_logging(dry_run: bool) -> None:
    _LOG_DIR.mkdir(exist_ok=True)
    log_file = _LOG_DIR / "meo.log"
    level = logging.DEBUG if dry_run else logging.INFO
    # Rotate at midnight JST (UTC+9); keep 14 daily files.
    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_file,
        when="midnight",
        utc=True,
        backupCount=14,
        encoding="utf-8",
    )
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        file_handler,
    ]
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="MEO automation — post & reply for all stores.")
    parser.add_argument("--dry-run", action="store_true", help="Log actions without making API writes.")
    parser.add_argument("--skip-posts", action="store_true", help="Skip local post creation.")
    parser.add_argument("--skip-reviews", action="store_true", help="Skip review reply posting.")
    parser.add_argument(
        "--store",
        metavar="STORE_KEY",
        nargs="+",
        help=(
            "Run only for the given store key(s). "
            "Keys: the_body_osaka_shinsaibashi, the_body_kyoto, mybear_studio_kyoto. "
            "Defaults to all stores."
        ),
    )
    args = parser.parse_args()

    _setup_logging(args.dry_run)
    logger = logging.getLogger(__name__)

    if args.dry_run:
        logger.info("=== DRY RUN MODE — no API writes will be made ===")

    logger.info("Validating configuration...")
    config_errors = validate_all()
    if config_errors:
        for e in config_errors:
            logger.error("Configuration error: %s", e)
        logger.critical(
            "%d configuration error(s) found. Fix the errors above and re-run.",
            len(config_errors),
        )
        sys.exit(1)

    logger.info("Authenticating with Google APIs...")
    try:
        creds = get_credentials()
    except EnvironmentError as exc:
        logger.critical("Auth failed: %s", exc)
        sys.exit(1)

    gbp = BusinessProfileClient(creds)
    drive = DriveClient(creds)
    stores = cfg.store_list()

    if args.store:
        known_keys = {s["key"] for s in stores}
        unknown = [k for k in args.store if k not in known_keys]
        if unknown:
            logger.error("Unknown store key(s): %s. Valid keys: %s", unknown, sorted(known_keys))
            sys.exit(1)
        stores = [s for s in stores if s["key"] in args.store]

    all_results: list[dict[str, Any]] = []
    had_error = False

    for store in stores:
        store_key = store["key"]
        store_results: dict[str, Any] = {"store_key": store_key}
        logger.info("=== Processing store: %s ===", store["name"])

        # Validate config before making any API calls
        if "TODO" in store.get("location_id", ""):
            logger.error(
                "[%s] location_id is not configured in config/stores.yaml. Skipping store.",
                store_key,
            )
            store_results["error"] = "location_id not configured"
            all_results.append(store_results)
            had_error = True
            continue
        if "TODO" in store.get("drive_folder_id", ""):
            logger.warning(
                "[%s] drive_folder_id is not configured — will post without photo.",
                store_key,
            )

        # --- Local posts ---
        if not args.skip_posts:
            try:
                post_result = run_post_for_store(store, gbp, drive, dry_run=args.dry_run)
                store_results["post"] = post_result
            except Exception as exc:
                logger.error("[%s] Post failed: %s", store_key, exc, exc_info=True)
                store_results["post"] = {"error": str(exc)}
                had_error = True

        # --- Review replies ---
        if not args.skip_reviews:
            try:
                review_result = run_reviews_for_store(store, gbp, dry_run=args.dry_run)
                store_results["reviews"] = review_result
                if review_result.get("errors"):
                    had_error = True
            except Exception as exc:
                logger.error("[%s] Reviews failed: %s", store_key, exc, exc_info=True)
                store_results["reviews"] = {"error": str(exc)}
                had_error = True

        all_results.append(store_results)

    # Summary
    logger.info("=== Run complete. Results: ===")
    for r in all_results:
        logger.info("  %s: %s", r["store_key"], r)

    send_run_summary(all_results, dry_run=args.dry_run)

    sys.exit(1 if had_error else 0)


if __name__ == "__main__":
    main()

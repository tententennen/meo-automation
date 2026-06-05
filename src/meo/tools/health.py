"""CLI: smoke-test Google API connectivity (read-only) before the first live run.

Usage:
    meo-health                            # or: python -m meo.tools.health
    meo-health --store the_body_kyoto     # single store

Checks per store (all read-only — no writes):
  - GBP API reachable: calls list_reviews() on the configured location
  - Drive API reachable: calls list_images() on the configured Drive folder

Exits 0 if every configured store passes all checks.
Exits 1 if any store fails a check or has an unconfigured location_id.
A missing drive_folder_id is flagged as a warning but does not fail the check
(posts can go out without photos).
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from meo import config as cfg
from meo.auth import get_credentials
from meo.business_profile import BusinessProfileClient
from meo.drive import DriveClient

_CHECK = "✓"
_CROSS = "✗"
_WARN = "!"


def run_health(store_keys: list[str] | None = None) -> list[dict[str, Any]]:
    """Run read-only connectivity checks for all (or selected) configured stores.

    Returns a list of per-store result dicts:
      {"store_key": str, "name": str, "checks": {label: result_str}, "ok": bool}

    On authentication failure, returns a single-element list with an "auth_error" key.
    """
    stores = cfg.store_list()
    if store_keys:
        stores = [s for s in stores if s["key"] in store_keys]

    try:
        creds = get_credentials()
    except EnvironmentError as exc:
        return [{"auth_error": str(exc)}]

    gbp = BusinessProfileClient(creds)
    drive = DriveClient(creds)

    results: list[dict[str, Any]] = []
    for store in stores:
        key = store["key"]
        location_id = store.get("location_id", "")
        folder_id = store.get("drive_folder_id", "")
        checks: dict[str, str] = {}
        store_ok = True

        if "TODO" in location_id or not location_id:
            checks["location_id"] = "not configured — run python -m meo.tools.discover_locations"
            store_ok = False
        else:
            try:
                reviews = gbp.list_reviews(location_id)
                checks["gbp_list_reviews"] = f"OK ({len(reviews)} review(s))"
            except Exception as exc:
                checks["gbp_list_reviews"] = f"ERROR: {exc}"
                store_ok = False

        if "TODO" in folder_id or not folder_id:
            # Not fatal — posts can go out without photos; flag as warning only.
            checks["drive_folder_id"] = "not configured — paste Google Drive folder ID in stores.yaml"
        else:
            try:
                images = drive.list_images(folder_id)
                checks["drive_list_images"] = f"OK ({len(images)} image(s))"
            except Exception as exc:
                checks["drive_list_images"] = f"ERROR: {exc}"
                store_ok = False

        results.append({
            "store_key": key,
            "name": store["name"],
            "checks": checks,
            "ok": store_ok,
        })

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smoke-test Google API connectivity (read-only) for all stores."
    )
    parser.add_argument(
        "--store",
        metavar="STORE_KEY",
        nargs="+",
        help="Check only these store key(s). Defaults to all configured stores.",
    )
    args = parser.parse_args()

    known_keys = {s["key"] for s in cfg.store_list()}
    if args.store:
        unknown = [k for k in args.store if k not in known_keys]
        if unknown:
            print(f"{_CROSS} Unknown store key(s): {unknown}")
            print(f"  Valid keys: {sorted(known_keys)}")
            sys.exit(1)

    print("=== MEO Health Check ===")
    print()

    results = run_health(args.store)

    if results and "auth_error" in results[0]:
        print(f"{_CROSS} Authentication failed: {results[0]['auth_error']}")
        print()
        print("Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REFRESH_TOKEN.")
        sys.exit(1)

    all_ok = True
    for r in results:
        sym = _CHECK if r["ok"] else _CROSS
        print(f"{sym} [{r['store_key']}] {r['name']}")
        for label, result in r["checks"].items():
            is_error = result.startswith("ERROR") or result.startswith("not configured")
            is_warn = label == "drive_folder_id" and result.startswith("not configured")
            if is_warn:
                check_sym = _WARN
            elif is_error:
                check_sym = _CROSS
            else:
                check_sym = _CHECK
            print(f"    {check_sym} {label}: {result}")
        if not r["ok"]:
            all_ok = False
        print()

    if all_ok:
        print("All checks passed. Ready for a live run.")
        sys.exit(0)
    else:
        print("Some checks failed. Fix the issues above before running live.")
        sys.exit(1)


if __name__ == "__main__":
    main()

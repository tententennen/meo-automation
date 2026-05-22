"""One-shot helper: list all GBP accounts and their locations.

Run once after Google API access is granted to find the location_id values
needed in config/stores.yaml.

Usage:
    python -m meo.tools.discover_locations

Output: a ready-to-paste YAML block for config/stores.yaml, plus the raw
        location names so you can match stores to IDs.

Required env vars (same set used by the main automation):
    GOOGLE_CLIENT_ID
    GOOGLE_CLIENT_SECRET
    GOOGLE_REFRESH_TOKEN

API refs:
  accounts:  https://developers.google.com/my-business/reference/businessinformation/rest/v1/accounts/list
  locations: https://developers.google.com/my-business/reference/businessinformation/rest/v1/accounts.locations/list
"""

from __future__ import annotations

import sys
import json

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from meo.auth import get_credentials

# Business Information API base
_ACCOUNTS_URL = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
_LOCATIONS_URL = (
    "https://mybusinessbusinessinformation.googleapis.com/v1/{account}/locations"
)
# Fields we want back
_LOCATION_FIELDS = "name,title,storefrontAddress,websiteUri"


def _get(session, url: str, params: dict | None = None):
    resp = session.get(url, params=params or {})
    if not resp.ok:
        print(f"  HTTP {resp.status_code}: {resp.text[:300]}", file=sys.stderr)
        resp.raise_for_status()
    return resp.json()


def main() -> None:
    print("Authenticating…")
    creds = get_credentials()

    # Build a thin requests session with auth headers
    from meo.business_profile import _AuthSession
    session = _AuthSession(creds)

    print("Fetching accounts…\n")
    accounts_data = _get(session, _ACCOUNTS_URL)
    accounts = accounts_data.get("accounts", [])
    if not accounts:
        print("No accounts found. Make sure the authenticated user has GBP account access.")
        sys.exit(1)

    all_locations: list[dict] = []

    for account in accounts:
        account_name = account.get("name", "")
        account_display = account.get("accountName", account_name)
        print(f"Account: {account_display}  ({account_name})")

        try:
            loc_data = _get(
                session,
                _LOCATIONS_URL.format(account=account_name),
                params={"readMask": _LOCATION_FIELDS, "pageSize": 100},
            )
        except Exception as exc:
            print(f"  Could not fetch locations: {exc}")
            continue

        locations = loc_data.get("locations", [])
        for loc in locations:
            loc["_account"] = account_name
            all_locations.append(loc)
            title = loc.get("title", "(no title)")
            loc_name = loc.get("name", "")
            print(f"  - {title}")
            print(f"    location_id: \"{loc_name}\"")

        if not locations:
            print("  (no locations)")
        print()

    if not all_locations:
        print("No locations found.")
        sys.exit(0)

    print("=" * 60)
    print("Paste the location_id values above into config/stores.yaml.")
    print()
    print("Example config/stores.yaml snippet:")
    print()
    for loc in all_locations:
        title = loc.get("title", "STORE NAME")
        loc_name = loc.get("name", "accounts/TODO/locations/TODO")
        print(f"  # {title}")
        print(f"  some_store_key:")
        print(f'    location_id: "{loc_name}"')
        print()


if __name__ == "__main__":
    main()

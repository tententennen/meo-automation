"""Google OAuth2 credentials via refresh-token flow.

Required environment variables (never commit their values):
  GOOGLE_CLIENT_ID      — OAuth 2.0 client ID (from Google Cloud Console)
  GOOGLE_CLIENT_SECRET  — OAuth 2.0 client secret
  GOOGLE_REFRESH_TOKEN  — Refresh token obtained during initial OAuth consent

One credential set covers both APIs via the combined scope list below.

To obtain a refresh token the first time (run once on a developer machine):
  1. Create an OAuth 2.0 Client ID (type: Desktop) in Google Cloud Console.
  2. Run:  python -m meo.auth
  3. Follow the browser prompt; the printed refresh token goes into your env.
"""

from __future__ import annotations

import os

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# Combined scopes: Business Profile read/write + Drive read-only
SCOPES = [
    "https://www.googleapis.com/auth/business.manage",
    "https://www.googleapis.com/auth/drive.readonly",
]

_TOKEN_URI = "https://oauth2.googleapis.com/token"


def get_credentials() -> Credentials:
    """Build and auto-refresh a Credentials object from environment variables."""
    client_id = _require_env("GOOGLE_CLIENT_ID")
    client_secret = _require_env("GOOGLE_CLIENT_SECRET")
    refresh_token = _require_env("GOOGLE_REFRESH_TOKEN")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=_TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    # Force an immediate token refresh so callers get a live access token.
    creds.refresh(Request())
    return creds


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{name}' is not set. "
            "See README.md § Environment Variables."
        )
    return value


# ---------------------------------------------------------------------------
# One-time setup helper — run `python -m meo.auth` to get a refresh token.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_id = _require_env("GOOGLE_CLIENT_ID")
    client_secret = _require_env("GOOGLE_CLIENT_SECRET")

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": _TOKEN_URI,
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
    creds = flow.run_local_server(port=0)
    print("\n=== Copy this refresh token into GOOGLE_REFRESH_TOKEN ===")
    print(creds.refresh_token)

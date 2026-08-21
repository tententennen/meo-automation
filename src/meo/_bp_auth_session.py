"""Authorized HTTP session for GBP API calls.

Internal module — not part of the public meo API.
"""

from __future__ import annotations

from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from google.oauth2.credentials import Credentials

from ._bp_constants import _DEFAULT_TIMEOUT


class _AuthSession:
    """A thin requests wrapper that injects a fresh Bearer token on each call.

    GET and PUT requests are automatically retried (up to 3 times with backoff)
    on transient failures (429, 5xx).  GET is safe to retry by definition; PUT
    is idempotent so retrying a failed reply_to_review never creates duplicates.
    POST is NOT retried — create_local_post is not idempotent and retrying would
    publish duplicate posts.

    All requests carry a (connect=10s, read=60s) timeout so the tool never
    hangs indefinitely on a stalled network connection.
    """

    def __init__(self, credentials: Credentials) -> None:
        self._creds = credentials
        self._session = requests.Session()
        # Retry GET (safe) and PUT (idempotent) on transient failures.
        # POST is excluded — retrying create_local_post would publish duplicate posts.
        _retry = Retry(
            total=3,
            backoff_factor=1.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "PUT"],
            raise_on_status=False,
        )
        self._session.mount("https://", HTTPAdapter(max_retries=_retry))

    def _refresh_if_needed(self) -> None:
        if not self._creds.valid:
            from google.auth.transport.requests import Request
            self._creds.refresh(Request())

    def _auth_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        """Return auth headers merged with any caller-supplied extra headers."""
        self._refresh_if_needed()
        headers = {"Authorization": f"Bearer {self._creds.token}"}
        if extra:
            headers.update(extra)
        return headers

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        extra = kwargs.pop("headers", None)
        kwargs.setdefault("timeout", _DEFAULT_TIMEOUT)
        return self._session.get(url, headers=self._auth_headers(extra), **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        extra = kwargs.pop("headers", None)
        kwargs.setdefault("timeout", _DEFAULT_TIMEOUT)
        return self._session.post(url, headers=self._auth_headers(extra), **kwargs)

    def put(self, url: str, **kwargs: Any) -> requests.Response:
        extra = kwargs.pop("headers", None)
        kwargs.setdefault("timeout", _DEFAULT_TIMEOUT)
        return self._session.put(url, headers=self._auth_headers(extra), **kwargs)

    def patch(self, url: str, **kwargs: Any) -> requests.Response:
        extra = kwargs.pop("headers", None)
        kwargs.setdefault("timeout", _DEFAULT_TIMEOUT)
        return self._session.patch(url, headers=self._auth_headers(extra), **kwargs)

    def delete(self, url: str, **kwargs: Any) -> requests.Response:
        extra = kwargs.pop("headers", None)
        kwargs.setdefault("timeout", _DEFAULT_TIMEOUT)
        return self._session.delete(url, headers=self._auth_headers(extra), **kwargs)

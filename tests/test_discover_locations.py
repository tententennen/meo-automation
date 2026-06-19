"""Tests for the discover_locations one-shot CLI helper.

The module is 0% covered by other tests because it requires live Google API
credentials.  These tests mock the HTTP layer so the logic can be exercised
without any network access.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_account(name: str = "accounts/1", display: str = "Test Business") -> dict:
    return {"name": name, "accountName": display}


def _fake_location(name: str = "accounts/1/locations/42", title: str = "THE BODY 京都店") -> dict:
    return {"name": name, "title": title}


def _fake_session(json_data, ok: bool = True, status_code: int = 200):
    """Return a mock session whose .get() always returns the given JSON."""
    resp = MagicMock()
    resp.ok = ok
    resp.status_code = status_code
    resp.text = "" if ok else "Error"
    resp.json.return_value = json_data
    if not ok:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    session = MagicMock()
    session.get.return_value = resp
    return session


# ---------------------------------------------------------------------------
# _get() helper
# ---------------------------------------------------------------------------

class TestGet:
    def test_returns_json_on_success(self):
        from meo.tools.discover_locations import _get
        session = _fake_session({"accounts": [{"name": "accounts/1"}]})
        result = _get(session, "https://example.com/v1/accounts")
        assert result == {"accounts": [{"name": "accounts/1"}]}

    def test_passes_empty_dict_when_no_params_given(self):
        from meo.tools.discover_locations import _get
        session = _fake_session({})
        _get(session, "https://example.com")
        session.get.assert_called_once_with("https://example.com", params={})

    def test_passes_params_when_given(self):
        from meo.tools.discover_locations import _get
        session = _fake_session({})
        _get(session, "https://example.com", params={"readMask": "name,title"})
        session.get.assert_called_once_with(
            "https://example.com", params={"readMask": "name,title"}
        )

    def test_raises_on_http_error(self):
        from meo.tools.discover_locations import _get
        session = _fake_session({}, ok=False, status_code=403)
        with pytest.raises(Exception, match="HTTP 403"):
            _get(session, "https://example.com")


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def _build_fake_get(accounts: list[dict], locations: list[dict]):
    """Return a side_effect for _get that dispatches by URL shape."""
    def fake_get(session, url: str, params=None):
        # The accounts list endpoint contains 'accounts' and NOT 'locations'
        if "locations" not in url:
            return {"accounts": accounts}
        return {"locations": locations}
    return fake_get


class TestMain:
    """Integration-style tests for discover_locations.main().

    All HTTP calls are replaced with _build_fake_get() so no network access
    or real credentials are needed.
    """

    def test_no_accounts_exits_1(self, capsys):
        from meo.tools.discover_locations import main
        with patch("meo.tools.discover_locations.get_credentials", return_value=MagicMock()), \
             patch("meo.tools.discover_locations._get", side_effect=_build_fake_get([], [])), \
             patch("meo.business_profile._AuthSession", return_value=MagicMock()):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "No accounts found" in out

    def test_account_with_locations_prints_location_id(self, capsys):
        from meo.tools.discover_locations import main
        account = _fake_account()
        loc = _fake_location()
        with patch("meo.tools.discover_locations.get_credentials", return_value=MagicMock()), \
             patch("meo.tools.discover_locations._get",
                   side_effect=_build_fake_get([account], [loc])), \
             patch("meo.business_profile._AuthSession", return_value=MagicMock()):
            main()  # returns normally — no sys.exit when locations are found
        out = capsys.readouterr().out
        assert "accounts/1/locations/42" in out
        assert "THE BODY 京都店" in out

    def test_account_with_no_locations_exits_0(self, capsys):
        from meo.tools.discover_locations import main
        account = _fake_account()
        with patch("meo.tools.discover_locations.get_credentials", return_value=MagicMock()), \
             patch("meo.tools.discover_locations._get",
                   side_effect=_build_fake_get([account], [])), \
             patch("meo.business_profile._AuthSession", return_value=MagicMock()):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "(no locations)" in out

    def test_location_fetch_error_is_caught_and_continues(self, capsys):
        """A 4xx/5xx on the locations endpoint must not crash — it is caught and skipped."""
        from meo.tools.discover_locations import main

        account = _fake_account()

        def fail_on_locations(session, url, params=None):
            if "locations" not in url:
                return {"accounts": [account]}
            raise RuntimeError("403 Forbidden")

        with patch("meo.tools.discover_locations.get_credentials", return_value=MagicMock()), \
             patch("meo.tools.discover_locations._get", side_effect=fail_on_locations), \
             patch("meo.business_profile._AuthSession", return_value=MagicMock()):
            with pytest.raises(SystemExit) as exc:
                main()
        # No locations were collected → sys.exit(0)
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "Could not fetch locations" in out

    def test_output_includes_yaml_snippet_for_found_locations(self, capsys):
        """main() must print a copy-paste YAML snippet containing the location name."""
        from meo.tools.discover_locations import main
        account = _fake_account()
        loc = _fake_location(name="accounts/1/locations/99", title="MYBEAR STUDIO 京都店")
        with patch("meo.tools.discover_locations.get_credentials", return_value=MagicMock()), \
             patch("meo.tools.discover_locations._get",
                   side_effect=_build_fake_get([account], [loc])), \
             patch("meo.business_profile._AuthSession", return_value=MagicMock()):
            main()
        out = capsys.readouterr().out
        assert 'location_id: "accounts/1/locations/99"' in out

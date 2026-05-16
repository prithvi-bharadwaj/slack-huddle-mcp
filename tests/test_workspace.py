"""Tests for slack_huddle.workspace — auth.test-based subdomain resolution."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from slack_huddle.api import AuthError, SlackApiError
from slack_huddle.workspace import resolve_workspace
from tests.conftest import TEST_XOXC, TEST_XOXD


@respx.mock
def test_resolve_workspace_uses_hint(auth_payload: dict[str, Any]) -> None:
    respx.post("https://myteam.slack.com/api/auth.test").mock(
        return_value=httpx.Response(200, json=auth_payload)
    )
    with httpx.Client() as http:
        info = resolve_workspace(TEST_XOXC, TEST_XOXD, hint="myteam", http_client=http)
    assert info.subdomain == "example"  # Comes from the response URL.
    assert info.team_id == "T00000001"
    assert info.team_name == "Example Workspace"


@respx.mock
def test_resolve_workspace_falls_back_to_slack_com(auth_payload: dict[str, Any]) -> None:
    respx.post("https://slack.com/api/auth.test").mock(
        return_value=httpx.Response(200, json=auth_payload)
    )
    with httpx.Client() as http:
        info = resolve_workspace(TEST_XOXC, TEST_XOXD, http_client=http)
    assert info.subdomain == "example"


@respx.mock
def test_resolve_workspace_uses_hint_when_url_missing() -> None:
    respx.post("https://myteam.slack.com/api/auth.test").mock(
        return_value=httpx.Response(
            200,
            json={"ok": True, "team": "X", "team_id": "T1", "user_id": "U1"},
        )
    )
    with httpx.Client() as http:
        info = resolve_workspace(TEST_XOXC, TEST_XOXD, hint="myteam", http_client=http)
    assert info.subdomain == "myteam"


@respx.mock
def test_resolve_workspace_normalizes_hint() -> None:
    respx.post("https://abc.slack.com/api/auth.test").mock(
        return_value=httpx.Response(200, json={"ok": True, "url": "https://abc.slack.com/"})
    )
    with httpx.Client() as http:
        info = resolve_workspace(
            TEST_XOXC, TEST_XOXD, hint="abc.slack.com", http_client=http
        )
    assert info.subdomain == "abc"


@respx.mock
def test_resolve_workspace_auth_error_on_401() -> None:
    respx.post("https://slack.com/api/auth.test").mock(return_value=httpx.Response(401))
    with httpx.Client() as http:
        with pytest.raises(AuthError):
            resolve_workspace(TEST_XOXC, TEST_XOXD, http_client=http)


@respx.mock
def test_resolve_workspace_auth_error_on_invalid_auth_code() -> None:
    respx.post("https://slack.com/api/auth.test").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "invalid_auth"})
    )
    with httpx.Client() as http:
        with pytest.raises(AuthError):
            resolve_workspace(TEST_XOXC, TEST_XOXD, http_client=http)


@respx.mock
def test_resolve_workspace_propagates_slack_error() -> None:
    respx.post("https://slack.com/api/auth.test").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "something_else"})
    )
    with httpx.Client() as http:
        with pytest.raises(SlackApiError):
            resolve_workspace(TEST_XOXC, TEST_XOXD, http_client=http)


@respx.mock
def test_resolve_workspace_missing_subdomain_raises() -> None:
    respx.post("https://slack.com/api/auth.test").mock(
        return_value=httpx.Response(200, json={"ok": True, "team": "X"})
    )
    with httpx.Client() as http:
        with pytest.raises(SlackApiError):
            resolve_workspace(TEST_XOXC, TEST_XOXD, http_client=http)


@respx.mock
def test_resolve_workspace_propagates_network_error() -> None:
    respx.post("https://slack.com/api/auth.test").mock(
        side_effect=httpx.ConnectError("boom")
    )
    with httpx.Client() as http:
        with pytest.raises(SlackApiError):
            resolve_workspace(TEST_XOXC, TEST_XOXD, http_client=http)

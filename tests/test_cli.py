"""Tests for the Click CLI."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from click.testing import CliRunner

from slack_huddle import keychain
from slack_huddle.cli import cli
from tests.conftest import TEST_WORKSPACE, TEST_XOXC, TEST_XOXD

BASE_URL = f"https://{TEST_WORKSPACE}.slack.com/api"


@pytest.fixture(autouse=True)
def _stub_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    state: dict[str, keychain.WorkspaceTokens] = {
        TEST_WORKSPACE: keychain.WorkspaceTokens(
            workspace=TEST_WORKSPACE, xoxc=TEST_XOXC, xoxd=TEST_XOXD
        ),
    }

    def _load(workspace: str) -> keychain.WorkspaceTokens:
        try:
            return state[workspace]
        except KeyError as exc:
            raise keychain.KeychainError(f"no tokens for {workspace}") from exc

    def _store(workspace: str, xoxc: str, xoxd: str) -> None:
        state[workspace] = keychain.WorkspaceTokens(
            workspace=workspace, xoxc=xoxc, xoxd=xoxd
        )

    monkeypatch.setattr(keychain, "load_tokens", _load)
    monkeypatch.setattr(keychain, "store_tokens", _store)
    monkeypatch.setattr(keychain, "default_workspace", lambda: TEST_WORKSPACE)
    monkeypatch.setattr(
        keychain, "list_workspaces", lambda: sorted(state.keys())
    )


@respx.mock
def test_status_shows_ok_for_each_workspace(auth_payload: dict[str, Any]) -> None:
    respx.post(f"{BASE_URL}/auth.test").mock(
        return_value=httpx.Response(200, json=auth_payload)
    )
    result = CliRunner().invoke(cli, ["status"])
    assert result.exit_code == 0
    assert "example: OK" in result.output


@respx.mock
def test_status_reports_auth_failure() -> None:
    respx.post(f"{BASE_URL}/auth.test").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "invalid_auth"})
    )
    result = CliRunner().invoke(cli, ["status"])
    assert result.exit_code == 0
    assert "AUTH_FAILED" in result.output


def test_status_when_no_workspaces(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keychain, "list_workspaces", lambda: [])
    result = CliRunner().invoke(cli, ["status"])
    assert result.exit_code == 0
    assert "No workspaces configured" in result.output


@respx.mock
def test_list_command_renders_table(huddles_history_payload: dict[str, Any]) -> None:
    respx.post(f"{BASE_URL}/huddles.history").mock(
        return_value=httpx.Response(200, json=huddles_history_payload)
    )
    result = CliRunner().invoke(cli, ["list", "--limit", "5"])
    assert result.exit_code == 0
    assert "H0000000001" in result.output
    assert "Min" in result.output


@respx.mock
def test_list_command_json_output(huddles_history_payload: dict[str, Any]) -> None:
    respx.post(f"{BASE_URL}/huddles.history").mock(
        return_value=httpx.Response(200, json=huddles_history_payload)
    )
    result = CliRunner().invoke(cli, ["list", "--json"])
    assert result.exit_code == 0
    assert "H0000000001" in result.output


@respx.mock
def test_list_command_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.post(f"{BASE_URL}/huddles.history").mock(
        return_value=httpx.Response(200, json={"ok": True, "huddles": []})
    )
    result = CliRunner().invoke(cli, ["list"])
    assert result.exit_code == 0
    assert "(no huddles)" in result.output


@respx.mock
def test_get_markdown_by_file_id(transcript_payload: dict[str, Any]) -> None:
    respx.post(f"{BASE_URL}/files.info").mock(
        return_value=httpx.Response(200, json=transcript_payload)
    )
    result = CliRunner().invoke(cli, ["get", "F0TRANSCRIPT01"])
    assert result.exit_code == 0
    assert "**U00000001**" in result.output


@respx.mock
def test_get_summary_by_canvas(canvas_payload: dict[str, Any]) -> None:
    respx.post(f"{BASE_URL}/files.info").mock(
        return_value=httpx.Response(200, json=canvas_payload)
    )
    result = CliRunner().invoke(cli, ["get", "F0CANVAS0001", "--format", "summary"])
    assert result.exit_code == 0
    assert "Lorem ipsum" in result.output


@respx.mock
def test_get_lines_format(transcript_payload: dict[str, Any]) -> None:
    respx.post(f"{BASE_URL}/files.info").mock(
        return_value=httpx.Response(200, json=transcript_payload)
    )
    result = CliRunner().invoke(cli, ["get", "F0TRANSCRIPT01", "--format", "lines"])
    assert result.exit_code == 0
    assert "speaker" in result.output


@respx.mock
def test_get_huddle_by_id(
    huddles_history_payload: dict[str, Any],
    canvas_payload: dict[str, Any],
    transcript_payload: dict[str, Any],
) -> None:
    respx.post(f"{BASE_URL}/huddles.history").mock(
        return_value=httpx.Response(200, json=huddles_history_payload)
    )
    respx.post(f"{BASE_URL}/files.info").mock(
        side_effect=[
            httpx.Response(200, json=canvas_payload),
            httpx.Response(200, json=transcript_payload),
        ]
    )
    result = CliRunner().invoke(cli, ["get", "H0000000001"])
    assert result.exit_code == 0
    assert "Lorem ipsum" in result.output


@respx.mock
def test_get_huddle_with_r_prefix_id(
    canvas_payload: dict[str, Any],
    transcript_payload: dict[str, Any],
) -> None:
    """Slack returns huddle IDs starting with `R` (legacy 'room' prefix)."""
    huddles_payload = {
        "ok": True,
        "huddles": [
            {
                "id": "R0B5CTD7FN2",
                "date_start": 1731499200,
                "date_end": 1731500700,
                "channels": ["C00000001"],
                "participant_history": [{"user_id": "U00000001"}],
                "transcript_file_id": "F0CANVAS0001",
                "huddle_link": "https://example.slack.com/huddle/T01/R0B5CTD7FN2",
            }
        ],
    }
    respx.post(f"{BASE_URL}/huddles.history").mock(
        return_value=httpx.Response(200, json=huddles_payload)
    )
    respx.post(f"{BASE_URL}/files.info").mock(
        side_effect=[
            httpx.Response(200, json=canvas_payload),
            httpx.Response(200, json=transcript_payload),
        ]
    )
    result = CliRunner().invoke(cli, ["get", "R0B5CTD7FN2"])
    assert result.exit_code == 0, result.output
    assert "Lorem ipsum" in result.output


@respx.mock
def test_smoke_test_skips_huddles_without_canvas(
    auth_payload: dict[str, Any],
    canvas_payload: dict[str, Any],
    transcript_payload: dict[str, Any],
) -> None:
    """Most recent huddle may not have a canvas yet; smoke-test should walk forward."""
    huddles_payload = {
        "ok": True,
        "huddles": [
            {"id": "R0NO_CANVAS_01", "date_start": 0, "date_end": 0, "channels": []},
            {
                "id": "R0HAS_CANVAS_2",
                "date_start": 0,
                "date_end": 0,
                "channels": ["C1"],
                "transcript_file_id": "F0CANVAS0001",
            },
        ],
    }
    respx.post(f"{BASE_URL}/auth.test").mock(
        return_value=httpx.Response(200, json=auth_payload)
    )
    respx.post(f"{BASE_URL}/huddles.history").mock(
        return_value=httpx.Response(200, json=huddles_payload)
    )
    respx.post(f"{BASE_URL}/files.info").mock(
        side_effect=[
            httpx.Response(200, json=canvas_payload),
            httpx.Response(200, json=transcript_payload),
        ]
    )
    result = CliRunner().invoke(cli, ["smoke-test"])
    assert result.exit_code == 0, result.output
    assert "skipped 1 recent huddle(s) without an AI canvas" in result.output
    assert "smoke-test: OK" in result.output


@respx.mock
def test_smoke_test_warns_when_no_huddle_has_canvas(
    auth_payload: dict[str, Any],
) -> None:
    huddles_payload = {
        "ok": True,
        "huddles": [
            {"id": "R0NO_CANVAS_01", "date_start": 0, "date_end": 0, "channels": []},
            {"id": "R0NO_CANVAS_02", "date_start": 0, "date_end": 0, "channels": []},
        ],
    }
    respx.post(f"{BASE_URL}/auth.test").mock(
        return_value=httpx.Response(200, json=auth_payload)
    )
    respx.post(f"{BASE_URL}/huddles.history").mock(
        return_value=httpx.Response(200, json=huddles_payload)
    )
    result = CliRunner().invoke(cli, ["smoke-test"])
    assert result.exit_code == 0, result.output
    assert "none of the" in result.output
    assert "have a canvas yet" in result.output


@respx.mock
def test_smoke_test_passes(
    auth_payload: dict[str, Any],
    huddles_history_payload: dict[str, Any],
    canvas_payload: dict[str, Any],
    transcript_payload: dict[str, Any],
) -> None:
    respx.post(f"{BASE_URL}/auth.test").mock(
        return_value=httpx.Response(200, json=auth_payload)
    )
    respx.post(f"{BASE_URL}/huddles.history").mock(
        return_value=httpx.Response(200, json=huddles_history_payload)
    )
    respx.post(f"{BASE_URL}/files.info").mock(
        side_effect=[
            httpx.Response(200, json=canvas_payload),
            httpx.Response(200, json=transcript_payload),
        ]
    )
    result = CliRunner().invoke(cli, ["smoke-test"])
    assert result.exit_code == 0
    assert "smoke-test: OK" in result.output


@respx.mock
def test_smoke_test_warns_on_no_huddles(auth_payload: dict[str, Any]) -> None:
    respx.post(f"{BASE_URL}/auth.test").mock(
        return_value=httpx.Response(200, json=auth_payload)
    )
    respx.post(f"{BASE_URL}/huddles.history").mock(
        return_value=httpx.Response(200, json={"ok": True, "huddles": []})
    )
    result = CliRunner().invoke(cli, ["smoke-test"])
    assert result.exit_code == 0
    assert "WARN no huddles" in result.output


def test_no_workspaces_raises_for_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keychain, "list_workspaces", lambda: [])
    monkeypatch.setattr(keychain, "default_workspace", lambda: None)
    result = CliRunner().invoke(cli, ["list"])
    assert result.exit_code != 0
    assert "No Slack workspaces" in result.output


def test_multiple_workspaces_requires_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keychain, "list_workspaces", lambda: ["a", "b"])
    monkeypatch.setattr(keychain, "default_workspace", lambda: None)
    result = CliRunner().invoke(cli, ["list"])
    assert result.exit_code != 0
    assert "Multiple workspaces" in result.output


@respx.mock
def test_setup_stores_tokens(auth_payload: dict[str, Any]) -> None:
    respx.post("https://example.slack.com/api/auth.test").mock(
        return_value=httpx.Response(200, json=auth_payload)
    )
    result = CliRunner().invoke(
        cli,
        ["setup", "--workspace", "example", "--xoxc", TEST_XOXC, "--xoxd", TEST_XOXD],
    )
    assert result.exit_code == 0, result.output
    assert "Stored tokens for workspace 'example'" in result.output


def test_setup_rejects_bad_xoxc() -> None:
    result = CliRunner().invoke(
        cli,
        ["setup", "--xoxc", "not-an-xoxc", "--xoxd", TEST_XOXD],
    )
    assert result.exit_code != 0
    assert "xoxc" in result.output


def test_serve_command_calls_main(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"yes": False}

    def fake_main() -> None:
        called["yes"] = True

    import slack_huddle.mcp_server as srv

    monkeypatch.setattr(srv, "main", fake_main)
    result = CliRunner().invoke(cli, ["serve"])
    assert result.exit_code == 0
    assert called["yes"]

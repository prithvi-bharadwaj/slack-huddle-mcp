"""Tests for the FastMCP server's tool surface.

These exercise the tool functions directly with a stubbed-out keychain so we
don't need real tokens. They also pin the FastMCP registration so MCP clients
keep seeing the same four tools.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from slack_huddle import keychain, mcp_server
from tests.conftest import TEST_WORKSPACE, TEST_XOXC, TEST_XOXD

BASE_URL = f"https://{TEST_WORKSPACE}.slack.com/api"


@pytest.fixture(autouse=True)
def _stub_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend we have tokens stored for ``example``."""

    def _load(workspace: str) -> keychain.WorkspaceTokens:
        return keychain.WorkspaceTokens(
            workspace=workspace,
            xoxc=TEST_XOXC,
            xoxd=TEST_XOXD,
        )

    monkeypatch.setattr(keychain, "load_tokens", _load)
    monkeypatch.setattr(keychain, "default_workspace", lambda: TEST_WORKSPACE)
    monkeypatch.setattr(keychain, "list_workspaces", lambda: [TEST_WORKSPACE])


@respx.mock
def test_list_huddles_shapes_records(huddles_history_payload: dict[str, Any]) -> None:
    respx.post(f"{BASE_URL}/huddles.history").mock(
        return_value=httpx.Response(200, json=huddles_history_payload)
    )
    huddles = mcp_server.list_huddles(channel_id="C00000001")
    assert len(huddles) == 2
    first = huddles[0]
    assert first["id"] == "H0000000001"
    assert first["channel_id"] == "C00000001"
    assert first["duration_min"] == 25.0
    assert first["attendees"] == ["U00000001", "U00000002", "U00000003"]
    assert first["transcript_canvas_id"] == "F0CANVAS0001"
    assert first["raw_transcript_file_id"] is None  # off by default
    assert first["date_start_iso"].endswith("+00:00")


@respx.mock
def test_list_huddles_resolves_transcript_file_ids(
    huddles_history_payload: dict[str, Any],
    canvas_payload: dict[str, Any],
) -> None:
    respx.post(f"{BASE_URL}/huddles.history").mock(
        return_value=httpx.Response(200, json=huddles_history_payload)
    )
    respx.post(f"{BASE_URL}/files.info").mock(
        return_value=httpx.Response(200, json=canvas_payload)
    )
    huddles = mcp_server.list_huddles(resolve_transcript_files=True)
    assert huddles[0]["raw_transcript_file_id"] == "F0TRANSCRIPT01"


@respx.mock
def test_get_huddle_transcript_markdown(
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
    text = mcp_server.get_huddle_transcript(
        huddle_id="H0000000001",
        format="markdown",
        user_map={"U00000001": "Alice"},
    )
    assert isinstance(text, str)
    assert "**Alice** [00:00]: Lorem ipsum" in text


@respx.mock
def test_get_huddle_transcript_json(transcript_payload: dict[str, Any]) -> None:
    respx.post(f"{BASE_URL}/files.info").mock(
        return_value=httpx.Response(200, json=transcript_payload)
    )
    payload = mcp_server.get_huddle_transcript(
        transcript_file_id="F0TRANSCRIPT01",
        format="json",
    )
    assert isinstance(payload, dict)
    assert "lines" in payload


@respx.mock
def test_get_huddle_transcript_lines(transcript_payload: dict[str, Any]) -> None:
    respx.post(f"{BASE_URL}/files.info").mock(
        return_value=httpx.Response(200, json=transcript_payload)
    )
    lines = mcp_server.get_huddle_transcript(
        transcript_file_id="F0TRANSCRIPT01",
        format="lines",
    )
    assert isinstance(lines, list)
    assert lines[0]["speaker"] == "U00000001"
    assert "text" in lines[0]


def test_get_huddle_transcript_requires_an_id() -> None:
    with pytest.raises(ValueError):
        mcp_server.get_huddle_transcript()


def test_get_huddle_transcript_rejects_bad_format() -> None:
    with pytest.raises(ValueError):
        mcp_server.get_huddle_transcript(
            transcript_file_id="F0X",
            format="csv",
        )


@respx.mock
def test_get_huddle_summary(canvas_payload: dict[str, Any]) -> None:
    respx.post(f"{BASE_URL}/files.info").mock(
        return_value=httpx.Response(200, json=canvas_payload)
    )
    summary = mcp_server.get_huddle_summary(canvas_id="F0CANVAS0001")
    assert "Lorem ipsum" in summary["summary_md"]
    assert summary["attendees"] == ["U00000001", "U00000002", "U00000003"]
    assert len(summary["action_items"]) == 2


def test_get_huddle_summary_requires_an_id() -> None:
    with pytest.raises(ValueError):
        mcp_server.get_huddle_summary()


def test_list_workspaces_returns_keychain_view() -> None:
    assert mcp_server.list_workspaces() == [TEST_WORKSPACE]


def test_required_tools_are_registered() -> None:
    """Lock the wire surface so MCP clients keep seeing the same names."""
    import anyio

    tools = anyio.run(mcp_server.mcp.list_tools)
    names = {tool.name for tool in tools}
    assert names == {
        "list_huddles",
        "get_huddle_transcript",
        "get_huddle_summary",
        "list_workspaces",
    }

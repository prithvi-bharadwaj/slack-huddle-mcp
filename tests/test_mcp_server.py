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
    respx.post(f"{BASE_URL}/files.info").mock(return_value=httpx.Response(200, json=canvas_payload))
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
    respx.post(f"{BASE_URL}/files.info").mock(return_value=httpx.Response(200, json=canvas_payload))
    summary = mcp_server.get_huddle_summary(canvas_id="F0CANVAS0001")
    assert "Lorem ipsum" in summary["summary_md"]
    assert summary["attendees"] == ["U00000001", "U00000002", "U00000003"]
    assert len(summary["action_items"]) == 2


CANVAS_HTML = (
    "<html><body><h1>:headphones: Notas do círculo</h1>"
    "<p>:handshake: Participantes</p><p>@U07SQPEA7GF, @U06MNN8L551 e @U0435GWR8B1</p>"
    "<p>:star: Resumo</p><p>Discutimos o sprint com muitos detalhes.</p></body></html>"
)


def _title_only_canvas_payload() -> dict[str, Any]:
    title = ":headphones: Notas do círculo: 24/8/26 no canal #C057VNWAZPE"
    return {
        "ok": True,
        "file": {
            "id": "F0CANVAS0001",
            "mimetype": "application/vnd.slack-docs",
            "is_huddle_canvas": True,
            "title": title,
            "plain_text": title,
            "url_private_download": "https://files.slack.com/files-pri/T000/F000/canvas",
            "permalink": "https://example.slack.com/docs/T000/F000",
        },
    }


@respx.mock
def test_get_huddle_summary_falls_back_to_canvas_html() -> None:
    respx.post(f"{BASE_URL}/files.info").mock(
        return_value=httpx.Response(200, json=_title_only_canvas_payload())
    )
    respx.get("https://files.slack.com/files-pri/T000/F000/canvas").mock(
        return_value=httpx.Response(200, text=CANVAS_HTML)
    )
    summary = mcp_server.get_huddle_summary(canvas_id="F0CANVAS0001")
    assert "Discutimos o sprint" in summary["summary_md"]
    # structured fields now parsed from the fetched markdown
    assert summary["attendees"] == ["U07SQPEA7GF", "U06MNN8L551", "U0435GWR8B1"]


@respx.mock
def test_get_huddle_summary_keeps_result_when_html_fails() -> None:
    respx.post(f"{BASE_URL}/files.info").mock(
        return_value=httpx.Response(200, json=_title_only_canvas_payload())
    )
    respx.get("https://files.slack.com/files-pri/T000/F000/canvas").mock(
        return_value=httpx.Response(500)
    )
    summary = mcp_server.get_huddle_summary(canvas_id="F0CANVAS0001")
    # title-only plain_text is treated as metadata, so graceful degradation is ""
    assert summary["summary_md"] == ""


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

"""Tests for slack_huddle.api — the 3-step pipeline and error paths."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from slack_huddle.api import (
    AuthError,
    RateLimitError,
    SlackApiError,
    SlackHuddleClient,
)
from tests.conftest import TEST_WORKSPACE, TEST_XOXC, TEST_XOXD

BASE_URL = f"https://{TEST_WORKSPACE}.slack.com/api"


def _client(http: httpx.Client) -> SlackHuddleClient:
    return SlackHuddleClient(
        xoxc_token=TEST_XOXC,
        xoxd_cookie=TEST_XOXD,
        workspace_subdomain=TEST_WORKSPACE,
        http_client=http,
        max_retries=2,
    )


def _captured_form(request: httpx.Request) -> dict[str, str]:
    body = request.content.decode("utf-8", errors="replace")
    form: dict[str, str] = {}
    # multipart bodies — strip headers, grab "name=...\r\n\r\n<value>" pairs.
    boundary = request.headers.get("content-type", "").split("boundary=")[-1]
    if not boundary:
        return form
    parts = body.split(f"--{boundary}")
    for part in parts:
        if "Content-Disposition" not in part or "name=" not in part:
            continue
        name = part.split('name="', 1)[1].split('"', 1)[0]
        value = part.split("\r\n\r\n", 1)[1].rsplit("\r\n", 1)[0]
        form[name] = value
    return form


def test_init_rejects_bad_token() -> None:
    with pytest.raises(ValueError):
        SlackHuddleClient(
            xoxc_token="not-an-xoxc-token",
            xoxd_cookie=TEST_XOXD,
            workspace_subdomain=TEST_WORKSPACE,
        )


def test_init_rejects_missing_cookie() -> None:
    with pytest.raises(ValueError):
        SlackHuddleClient(
            xoxc_token=TEST_XOXC,
            xoxd_cookie="",
            workspace_subdomain=TEST_WORKSPACE,
        )


def test_init_rejects_missing_workspace() -> None:
    with pytest.raises(ValueError):
        SlackHuddleClient(
            xoxc_token=TEST_XOXC,
            xoxd_cookie=TEST_XOXD,
            workspace_subdomain="",
        )


@respx.mock
def test_request_shape_carries_token_and_cookie(auth_payload: dict[str, Any]) -> None:
    route = respx.post(f"{BASE_URL}/auth.test").mock(
        return_value=httpx.Response(200, json=auth_payload)
    )
    with httpx.Client() as http, _client(http) as client:
        client.auth_test()

    assert route.called
    request = route.calls[0].request
    assert request.headers["Cookie"] == f"d={TEST_XOXD}"
    form = _captured_form(request)
    assert form["token"].startswith("xoxc-")


@respx.mock
def test_huddles_history_returns_huddles_list(huddles_history_payload: dict[str, Any]) -> None:
    respx.post(f"{BASE_URL}/huddles.history").mock(
        return_value=httpx.Response(200, json=huddles_history_payload)
    )
    with httpx.Client() as http, _client(http) as client:
        huddles = client.huddles_history(channel_id="C00000001", limit=10)
    assert len(huddles) == 2
    assert huddles[0]["id"] == "H0000000001"
    assert huddles[0]["transcript_file_id"] == "F0CANVAS0001"


@respx.mock
def test_huddles_history_empty_when_missing() -> None:
    respx.post(f"{BASE_URL}/huddles.history").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    with httpx.Client() as http, _client(http) as client:
        assert client.huddles_history() == []


@respx.mock
def test_huddles_history_filters_non_dicts() -> None:
    respx.post(f"{BASE_URL}/huddles.history").mock(
        return_value=httpx.Response(
            200, json={"ok": True, "huddles": [{"id": "H1"}, "garbage", None]}
        )
    )
    with httpx.Client() as http, _client(http) as client:
        huddles = client.huddles_history()
    assert huddles == [{"id": "H1"}]


@respx.mock
def test_files_info_basic(canvas_payload: dict[str, Any]) -> None:
    route = respx.post(f"{BASE_URL}/files.info").mock(
        return_value=httpx.Response(200, json=canvas_payload)
    )
    with httpx.Client() as http, _client(http) as client:
        file_obj = client.files_info("F0CANVAS0001")

    assert file_obj["id"] == "F0CANVAS0001"
    form = _captured_form(route.calls[0].request)
    assert form["file"] == "F0CANVAS0001"
    assert form["include_transcription"] == "false"


@respx.mock
def test_files_info_with_include_transcription(transcript_payload: dict[str, Any]) -> None:
    route = respx.post(f"{BASE_URL}/files.info").mock(
        return_value=httpx.Response(200, json=transcript_payload)
    )
    with httpx.Client() as http, _client(http) as client:
        file_obj = client.files_info("F0TRANSCRIPT01", include_transcription=True)

    form = _captured_form(route.calls[0].request)
    assert form["include_transcription"] == "true"
    assert form["page"] == "1"
    assert form["count"] == "500"
    assert form["truncate"] == "true"
    assert file_obj["huddle_transcription"]["channel_id"] == "C00000001"


@respx.mock
def test_files_info_raises_when_file_missing() -> None:
    respx.post(f"{BASE_URL}/files.info").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    with httpx.Client() as http, _client(http) as client:
        with pytest.raises(SlackApiError) as exc_info:
            client.files_info("F0X")
    assert "missing_file" in exc_info.value.error


@respx.mock
def test_resolve_transcript_file_id(canvas_payload: dict[str, Any]) -> None:
    respx.post(f"{BASE_URL}/files.info").mock(
        return_value=httpx.Response(200, json=canvas_payload)
    )
    with httpx.Client() as http, _client(http) as client:
        transcript_id = client.resolve_transcript_file_id("F0CANVAS0001")
    assert transcript_id == "F0TRANSCRIPT01"


@respx.mock
def test_resolve_transcript_file_id_missing_field() -> None:
    respx.post(f"{BASE_URL}/files.info").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "file": {"id": "F0CANVAS0001", "is_huddle_canvas": True},
            },
        )
    )
    with httpx.Client() as http, _client(http) as client:
        with pytest.raises(SlackApiError) as exc_info:
            client.resolve_transcript_file_id("F0CANVAS0001")
    assert exc_info.value.error == "missing_huddle_transcript_file_id"


@respx.mock
def test_fetch_transcription(transcript_payload: dict[str, Any]) -> None:
    respx.post(f"{BASE_URL}/files.info").mock(
        return_value=httpx.Response(200, json=transcript_payload)
    )
    with httpx.Client() as http, _client(http) as client:
        transcription = client.fetch_transcription("F0TRANSCRIPT01")
    assert "lines" in transcription
    assert len(transcription["lines"]) == 6


@respx.mock
def test_fetch_transcription_missing_payload() -> None:
    respx.post(f"{BASE_URL}/files.info").mock(
        return_value=httpx.Response(
            200, json={"ok": True, "file": {"id": "F0X"}}
        )
    )
    with httpx.Client() as http, _client(http) as client:
        with pytest.raises(SlackApiError) as exc_info:
            client.fetch_transcription("F0X")
    assert exc_info.value.error == "missing_huddle_transcription"


@respx.mock
def test_fetch_huddle_summary_canvas(canvas_payload: dict[str, Any]) -> None:
    respx.post(f"{BASE_URL}/files.info").mock(
        return_value=httpx.Response(200, json=canvas_payload)
    )
    with httpx.Client() as http, _client(http) as client:
        canvas = client.fetch_huddle_summary_canvas("F0CANVAS0001")
    assert canvas["is_huddle_canvas"] is True


@respx.mock
def test_fetch_huddle_summary_canvas_rejects_non_canvas() -> None:
    respx.post(f"{BASE_URL}/files.info").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "file": {"id": "F0X", "is_huddle_canvas": False, "mimetype": "text/plain"},
            },
        )
    )
    with httpx.Client() as http, _client(http) as client:
        with pytest.raises(SlackApiError) as exc_info:
            client.fetch_huddle_summary_canvas("F0X")
    assert exc_info.value.error == "not_a_huddle_canvas"


@respx.mock
def test_auth_error_on_401() -> None:
    respx.post(f"{BASE_URL}/auth.test").mock(return_value=httpx.Response(401))
    with httpx.Client() as http, _client(http) as client:
        with pytest.raises(AuthError):
            client.auth_test()


@respx.mock
def test_auth_error_on_403() -> None:
    respx.post(f"{BASE_URL}/auth.test").mock(return_value=httpx.Response(403))
    with httpx.Client() as http, _client(http) as client:
        with pytest.raises(AuthError):
            client.auth_test()


@respx.mock
def test_auth_error_on_invalid_auth_code() -> None:
    respx.post(f"{BASE_URL}/auth.test").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "invalid_auth"})
    )
    with httpx.Client() as http, _client(http) as client:
        with pytest.raises(AuthError):
            client.auth_test()


@respx.mock
def test_slack_error_for_unknown_code() -> None:
    respx.post(f"{BASE_URL}/auth.test").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "wat"})
    )
    with httpx.Client() as http, _client(http) as client:
        with pytest.raises(SlackApiError) as exc_info:
            client.auth_test()
    assert exc_info.value.error == "wat"


@respx.mock
def test_rate_limit_retries_then_raises() -> None:
    respx.post(f"{BASE_URL}/auth.test").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "0"})
    )
    with httpx.Client() as http, _client(http) as client:
        with pytest.raises(RateLimitError):
            client.auth_test()


@respx.mock
def test_rate_limit_recovers(auth_payload: dict[str, Any]) -> None:
    responses = [
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(200, json=auth_payload),
    ]
    route = respx.post(f"{BASE_URL}/auth.test").mock(side_effect=responses)
    with httpx.Client() as http, _client(http) as client:
        data = client.auth_test()
    assert data["ok"] is True
    assert route.call_count == 2


@respx.mock
def test_slack_ratelimited_code_recovers(auth_payload: dict[str, Any]) -> None:
    responses = [
        httpx.Response(200, json={"ok": False, "error": "ratelimited", "retry_after": 0}),
        httpx.Response(200, json=auth_payload),
    ]
    route = respx.post(f"{BASE_URL}/auth.test").mock(side_effect=responses)
    with httpx.Client() as http, _client(http) as client:
        client.auth_test()
    assert route.call_count == 2


@respx.mock
def test_server_error_retries_then_raises() -> None:
    respx.post(f"{BASE_URL}/auth.test").mock(return_value=httpx.Response(500))
    with httpx.Client() as http, _client(http) as client:
        with pytest.raises(SlackApiError):
            client.auth_test()


@respx.mock
def test_invalid_json_raises() -> None:
    respx.post(f"{BASE_URL}/auth.test").mock(
        return_value=httpx.Response(200, content=b"not-json")
    )
    with httpx.Client() as http, _client(http) as client:
        with pytest.raises(SlackApiError) as exc_info:
            client.auth_test()
    assert "invalid_json" in exc_info.value.error


@respx.mock
def test_network_error_retries_then_raises() -> None:
    respx.post(f"{BASE_URL}/auth.test").mock(
        side_effect=httpx.ConnectError("boom")
    )
    with httpx.Client() as http, _client(http) as client:
        with pytest.raises(SlackApiError):
            client.auth_test()


@respx.mock
def test_skips_none_form_values(huddles_history_payload: dict[str, Any]) -> None:
    route = respx.post(f"{BASE_URL}/huddles.history").mock(
        return_value=httpx.Response(200, json=huddles_history_payload)
    )
    with httpx.Client() as http, _client(http) as client:
        client.huddles_history()
    form = _captured_form(route.calls[0].request)
    assert "channel" not in form
    assert "oldest" not in form
    assert form["limit"] == "50"


def test_request_form_serializes_json_safely(huddles_history_payload: dict[str, Any]) -> None:
    """Round-trip the canned huddles fixture stays parseable."""
    serialized = json.dumps(huddles_history_payload)
    assert "U00000001" in serialized
    assert "xoxc" not in serialized

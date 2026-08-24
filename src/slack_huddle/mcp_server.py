"""FastMCP server exposing Slack huddle transcripts to MCP clients."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastmcp import FastMCP

from slack_huddle import keychain
from slack_huddle.api import SlackHuddleClient
from slack_huddle.parser import (
    SpeakerTurn,
    extract_summary_from_canvas,
    format_lines,
    format_markdown,
    parse_transcription,
)

logger = logging.getLogger(__name__)

mcp: FastMCP = FastMCP(
    "slack-huddle",
    instructions=(
        "Read Slack huddle AI transcripts and AI summaries. Slack's web UI generates "
        "these automatically for huddles on Pro/Business+ workspaces; this server "
        "exposes them via the same internal endpoints the Slack web client uses. "
        "Tokens are loaded from the OS keychain — never hardcode tokens here."
    ),
)


def _resolve_workspace(workspace: str | None) -> str:
    if workspace:
        return workspace.strip().lower()
    default = keychain.default_workspace()
    if default is None:
        workspaces = keychain.list_workspaces()
        if not workspaces:
            raise RuntimeError(
                "No Slack workspaces configured. Run `slack-huddle-mcp setup` first."
            )
        raise RuntimeError(
            "Multiple workspaces configured ("
            + ", ".join(workspaces)
            + "); pass `workspace` explicitly."
        )
    return default


def _client(workspace: str | None) -> SlackHuddleClient:
    ws = _resolve_workspace(workspace)
    tokens = keychain.load_tokens(ws)
    return SlackHuddleClient(
        xoxc_token=tokens.xoxc,
        xoxd_cookie=tokens.xoxd,
        workspace_subdomain=ws,
    )


def _iso(ts: float | int | None) -> str:
    if ts is None:
        return ""
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def _shape_huddle(raw: dict[str, Any]) -> dict[str, Any]:
    date_start = raw.get("date_start")
    date_end = raw.get("date_end")
    duration_min = 0.0
    if isinstance(date_start, (int, float)) and isinstance(date_end, (int, float)):
        duration_min = max(0.0, round((float(date_end) - float(date_start)) / 60.0, 2))

    channels = raw.get("channels")
    channel_id = ""
    if isinstance(channels, list) and channels:
        first = channels[0]
        if isinstance(first, str):
            channel_id = first
        elif isinstance(first, dict):
            channel_id = str(first.get("id", ""))

    attendees: list[str] = []
    participant_history = raw.get("participant_history")
    if isinstance(participant_history, list):
        for p in participant_history:
            if isinstance(p, dict):
                user_id = p.get("user_id") or p.get("user")
                if isinstance(user_id, str) and user_id not in attendees:
                    attendees.append(user_id)
            elif isinstance(p, str) and p not in attendees:
                attendees.append(p)

    return {
        "id": str(raw.get("id", "")),
        "channel_id": channel_id,
        "date_start_iso": _iso(date_start),
        "date_end_iso": _iso(date_end),
        "duration_min": duration_min,
        "attendees": attendees,
        "transcript_canvas_id": str(raw.get("transcript_file_id", "")),
        "raw_transcript_file_id": None,
        "huddle_link": str(raw.get("huddle_link", "")),
        "thread_root_ts": str(raw.get("thread_root_ts", "")),
    }


@mcp.tool()
def list_huddles(
    channel_id: str | None = None,
    after: float | None = None,
    before: float | None = None,
    limit: int = 50,
    workspace: str | None = None,
    resolve_transcript_files: bool = False,
) -> list[dict[str, Any]]:
    """List recent Slack huddles, optionally scoped to a channel.

    Returns a list of huddle records with id, channel_id, ISO start/end times,
    duration in minutes, attendees, canvas/transcript file ids, and the huddle link.

    Args:
        channel_id: Slack channel ID (e.g. ``C00000001``). Omit for workspace-wide.
        after: Unix-seconds lower bound on ``date_start`` (Slack's ``oldest``).
        before: Unix-seconds upper bound on ``date_start`` (Slack's ``latest``).
        limit: Maximum huddles to return (default 50).
        workspace: Workspace subdomain. Optional when only one is configured.
        resolve_transcript_files: When True, also fetch each huddle's canvas to
            populate ``raw_transcript_file_id``. Off by default (N+1 API calls).
    """
    with _client(workspace) as client:
        raw_huddles = client.huddles_history(
            channel_id=channel_id, limit=limit, oldest=after, latest=before
        )
        shaped = [_shape_huddle(h) for h in raw_huddles]
        if resolve_transcript_files:
            for huddle in shaped:
                canvas_id = huddle["transcript_canvas_id"]
                if not canvas_id:
                    continue
                try:
                    huddle["raw_transcript_file_id"] = client.resolve_transcript_file_id(
                        canvas_id
                    )
                except Exception:
                    logger.debug("could not resolve transcript file id for %s", canvas_id)
                    huddle["raw_transcript_file_id"] = None
        return shaped


@mcp.tool()
def get_huddle_transcript(
    huddle_id: str | None = None,
    transcript_file_id: str | None = None,
    format: str = "markdown",
    merge_consecutive: bool = True,
    user_map: dict[str, str] | None = None,
    workspace: str | None = None,
) -> Any:
    """Fetch the AI transcript for one huddle.

    Provide exactly one of ``huddle_id`` (looked up via ``huddles.history`` and the
    canvas chain) or ``transcript_file_id`` (the raw transcript file, mimetype
    ``application/vnd.slack-huddle-transcript``).

    Args:
        huddle_id: Huddle ID from ``list_huddles`` (e.g. ``H0000000001``).
        transcript_file_id: Raw transcript file ID, if already known.
        format: ``markdown`` (default), ``json`` (raw payload), or ``lines``.
        merge_consecutive: Merge adjacent same-speaker lines (default True).
        user_map: Optional ``{slack_user_id: display_name}`` for nicer output.
        workspace: Workspace subdomain. Optional when only one is configured.
    """
    if not huddle_id and not transcript_file_id:
        raise ValueError("Either huddle_id or transcript_file_id is required")
    if format not in ("markdown", "json", "lines"):
        raise ValueError(f"unsupported format: {format!r} (use markdown/json/lines)")

    with _client(workspace) as client:
        resolved_file_id = transcript_file_id
        if not resolved_file_id:
            assert huddle_id is not None
            canvas_id = _find_canvas_id(client, huddle_id)
            resolved_file_id = client.resolve_transcript_file_id(canvas_id)

        transcription = client.fetch_transcription(resolved_file_id)

        if format == "json":
            return transcription

        turns = parse_transcription(transcription, merge_consecutive=merge_consecutive)
        if format == "lines":
            return format_lines(turns, user_map=user_map)
        return format_markdown(turns, user_map=user_map)


@mcp.tool()
def get_huddle_summary(
    canvas_id: str | None = None,
    huddle_id: str | None = None,
    workspace: str | None = None,
) -> dict[str, Any]:
    """Fetch the AI-generated huddle summary canvas.

    Returns ``{summary_md, action_items, attendees, canvas_url}``. Provide either
    ``canvas_id`` directly or ``huddle_id`` (resolved via ``huddles.history``).
    """
    if not canvas_id and not huddle_id:
        raise ValueError("Either canvas_id or huddle_id is required")

    with _client(workspace) as client:
        if not canvas_id:
            assert huddle_id is not None
            canvas_id = _find_canvas_id(client, huddle_id)
        canvas = client.fetch_huddle_summary_canvas(canvas_id)
        result = extract_summary_from_canvas(canvas)
        # single trigger — files.info returning title-length text means a
        # metadata-only canvas; fetch the rendered HTML instead
        # (fetch_canvas_html returns None when there's no URL). Replaces
        # shorter text only.
        if len(result["summary_md"]) < 500:
            try:
                html = client.fetch_canvas_html(canvas)
                if html:
                    from slack_huddle.parser import canvas_html_to_markdown

                    md = canvas_html_to_markdown(html)
                    if len(md) > len(result["summary_md"]):
                        # re-extract so attendees/action_items parse from the full md
                        result = extract_summary_from_canvas(canvas, summary_md_override=md)
            except Exception:
                logger.debug("canvas HTML fallback failed for %s", canvas_id, exc_info=True)
        return result


@mcp.tool()
def list_workspaces() -> list[str]:
    """List all Slack workspaces with stored tokens on this machine."""
    return keychain.list_workspaces()


def _find_canvas_id(client: SlackHuddleClient, huddle_id: str) -> str:
    """Walk ``huddles.history`` until we find ``huddle_id``; return its canvas file id."""
    huddles = client.huddles_history(limit=200)
    for huddle in huddles:
        if huddle.get("id") == huddle_id:
            canvas_id = huddle.get("transcript_file_id")
            if isinstance(canvas_id, str) and canvas_id:
                return canvas_id
            raise RuntimeError(f"huddle {huddle_id} has no transcript_file_id")
    raise RuntimeError(
        f"huddle {huddle_id} not found in recent history; pass transcript_file_id instead"
    )


# Re-export the model for downstream consumers (tests, type-checkers).
__all__ = [
    "SpeakerTurn",
    "get_huddle_summary",
    "get_huddle_transcript",
    "list_huddles",
    "list_workspaces",
    "mcp",
]


def main(
    *,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
    http_path: str = "/mcp",
) -> None:
    """Entrypoint for ``python -m slack_huddle.mcp_server``.

    ``transport`` can be ``stdio`` (default, for Claude Code / Desktop) or
    ``http`` (streamable HTTP, for Claude.ai/Cowork via a public tunnel).

    ``http_path`` lets the caller move the MCP endpoint to a secret URL like
    ``/mcp/<random-token>``. Requests to any other path return 404 — this is
    the simplest auth model that works with Cowork's connector UI (which
    doesn't expose custom-header configuration). Treat the path as a
    bearer token: anyone who can guess it can call your tools.
    """
    logging.basicConfig(level=logging.WARNING)
    if transport == "stdio":
        mcp.run()
    elif transport == "http":
        logger.info("starting streamable HTTP server on %s:%d%s", host, port, http_path)
        mcp.run(transport="http", host=host, port=port, path=http_path)
    else:
        raise ValueError(f"unsupported transport: {transport!r}")


if __name__ == "__main__":
    main()

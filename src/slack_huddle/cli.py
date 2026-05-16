"""Click CLI: ``setup``, ``list``, ``get``, ``smoke-test``, ``status``."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

import click

from slack_huddle import keychain
from slack_huddle.api import AuthError, SlackApiError, SlackHuddleClient
from slack_huddle.parser import (
    extract_summary_from_canvas,
    format_lines,
    format_markdown,
    parse_transcription,
)
from slack_huddle.workspace import resolve_workspace

logger = logging.getLogger(__name__)


def _stderr(*parts: Any) -> None:
    click.echo(" ".join(str(p) for p in parts), err=True)


def _resolve_workspace_name(workspace: str | None) -> str:
    if workspace:
        return workspace.strip().lower()
    default = keychain.default_workspace()
    if default:
        return default
    workspaces = keychain.list_workspaces()
    if not workspaces:
        raise click.ClickException(
            "No Slack workspaces configured. Run `slack-huddle-mcp setup` first."
        )
    raise click.ClickException(
        "Multiple workspaces configured: "
        + ", ".join(workspaces)
        + ". Pass --workspace explicitly."
    )


def _open_client(workspace: str | None) -> SlackHuddleClient:
    ws = _resolve_workspace_name(workspace)
    tokens = keychain.load_tokens(ws)
    return SlackHuddleClient(
        xoxc_token=tokens.xoxc,
        xoxd_cookie=tokens.xoxd,
        workspace_subdomain=ws,
    )


@click.group()
@click.version_option(package_name="slack-huddle-mcp")
def cli() -> None:
    """Expose Slack AI huddle transcripts via MCP."""


@cli.command()
@click.option("--workspace", "-w", help="Workspace subdomain (e.g. myteam).")
@click.option("--xoxc", help="xoxc token (skip prompt).")
@click.option("--xoxd", help="xoxd cookie value (skip prompt).")
def setup(workspace: str | None, xoxc: str | None, xoxd: str | None) -> None:
    """Walk through token extraction and save to the OS keychain."""
    click.echo(
        "\n"
        "Slack-huddle-mcp setup\n"
        "----------------------\n"
        "We need two tokens from your Slack web client. They live in your\n"
        "browser only — Slack does not give them out programmatically.\n"
    )
    if not xoxc:
        click.echo(
            "Step 1: open Slack in your browser, log in, then open DevTools console.\n"
            "Paste this snippet and copy the result:\n\n"
            "  JSON.parse(localStorage.localConfig_v2).teams[\n"
            "    Object.keys(JSON.parse(localStorage.localConfig_v2).teams)[0]\n"
            "  ].token\n"
        )
        xoxc = click.prompt("Paste xoxc token", type=str, hide_input=True).strip()
    if not xoxc.startswith("xoxc-"):
        raise click.ClickException("token does not look like an xoxc- token")

    if not xoxd:
        click.echo(
            "\nStep 2: in DevTools open Application -> Cookies -> https://app.slack.com\n"
            "Find the cookie named `d` (HttpOnly). Copy its raw value (do not URL-decode).\n"
        )
        xoxd = click.prompt("Paste xoxd cookie value", type=str, hide_input=True).strip()
    if not xoxd:
        raise click.ClickException("xoxd cookie is required")

    click.echo("\nValidating tokens via auth.test ...")
    try:
        info = resolve_workspace(xoxc, xoxd, hint=workspace)
    except AuthError as exc:
        raise click.ClickException(f"auth failed: {exc.error}") from exc
    except SlackApiError as exc:
        raise click.ClickException(f"workspace resolution failed: {exc.error}") from exc

    keychain.store_tokens(info.subdomain, xoxc, xoxd)
    click.echo(
        f"\nStored tokens for workspace '{info.subdomain}' "
        f"(team={info.team_name or info.team_id})."
    )
    click.echo("\nMCP config snippet:\n")
    click.echo(_mcp_config_snippet())


@cli.command(name="list")
@click.option("--workspace", "-w", help="Workspace subdomain.")
@click.option("--channel", "-c", help="Channel ID to filter on.")
@click.option("--limit", "-n", default=20, type=int, help="Maximum huddles to show.")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON instead of a table.")
def list_cmd(workspace: str | None, channel: str | None, limit: int, as_json: bool) -> None:
    """List recent huddles."""
    with _open_client(workspace) as client:
        try:
            huddles = client.huddles_history(channel_id=channel, limit=limit)
        except AuthError as exc:
            raise click.ClickException(_auth_help(exc)) from exc
        except SlackApiError as exc:
            raise click.ClickException(f"slack error: {exc.error}") from exc

    if as_json:
        click.echo(json.dumps(huddles, indent=2, sort_keys=True))
        return

    if not huddles:
        click.echo("(no huddles)")
        return

    click.echo(f"{'ID':<24} {'When (UTC)':<25} {'Min':>5}  Channel")
    click.echo("-" * 80)
    for huddle in huddles:
        when = _iso(huddle.get("date_start"))
        duration = _duration_min(huddle)
        channels = huddle.get("channels") or []
        channel_id = channels[0] if channels and isinstance(channels[0], str) else ""
        click.echo(
            f"{huddle.get('id', ''):<24} {when:<25} {duration:>5}  {channel_id}"
        )


@cli.command(name="get")
@click.argument("huddle_or_file_id")
@click.option("--workspace", "-w", help="Workspace subdomain.")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json", "lines", "summary"]),
    default="markdown",
)
@click.option("--no-merge", is_flag=True, help="Don't merge consecutive same-speaker lines.")
def get_cmd(
    huddle_or_file_id: str, workspace: str | None, fmt: str, no_merge: bool
) -> None:
    """Print a huddle's transcript or summary.

    Accepts either a huddle ID (e.g. ``H0...``) or a transcript file ID (``F0...``).
    """
    with _open_client(workspace) as client:
        try:
            file_id = _resolve_to_transcript_file(client, huddle_or_file_id)

            if fmt == "summary":
                canvas_id = _resolve_to_canvas(client, huddle_or_file_id)
                canvas = client.fetch_huddle_summary_canvas(canvas_id)
                click.echo(json.dumps(extract_summary_from_canvas(canvas), indent=2))
                return

            transcription = client.fetch_transcription(file_id)
            if fmt == "json":
                click.echo(json.dumps(transcription, indent=2, sort_keys=True))
                return
            turns = parse_transcription(transcription, merge_consecutive=not no_merge)
            if fmt == "lines":
                click.echo(json.dumps(format_lines(turns), indent=2))
                return
            click.echo(format_markdown(turns))
        except AuthError as exc:
            raise click.ClickException(_auth_help(exc)) from exc
        except SlackApiError as exc:
            raise click.ClickException(f"slack error: {exc.error}") from exc


@cli.command(name="smoke-test")
@click.option("--workspace", "-w", help="Workspace subdomain.")
def smoke_test_cmd(workspace: str | None) -> None:
    """End-to-end check: list -> resolve canvas -> fetch transcription on the latest huddle."""
    with _open_client(workspace) as client:
        ws_name = client.workspace_subdomain
        click.echo(f"[1/4] auth.test against {ws_name} ...")
        try:
            auth = client.auth_test()
        except AuthError as exc:
            click.echo(f"  FAIL auth: {exc.error}")
            sys.exit(1)
        click.echo(
            f"  OK team={auth.get('team', '?')} user_id={auth.get('user_id', '?')}"
        )

        click.echo("[2/4] huddles.history ...")
        try:
            huddles = client.huddles_history(limit=5)
        except SlackApiError as exc:
            click.echo(f"  FAIL: {exc.error}")
            sys.exit(1)
        if not huddles:
            click.echo("  WARN no huddles found; cannot complete transcript check.")
            sys.exit(0)
        first = huddles[0]
        click.echo(f"  OK {len(huddles)} huddles; first={first.get('id', '?')}")

        canvas_id = first.get("transcript_file_id")
        if not isinstance(canvas_id, str) or not canvas_id:
            click.echo("  FAIL first huddle is missing transcript_file_id")
            sys.exit(1)

        click.echo(f"[3/4] resolve canvas {canvas_id} -> raw transcript file ...")
        try:
            transcript_file_id = client.resolve_transcript_file_id(canvas_id)
        except SlackApiError as exc:
            click.echo(f"  FAIL: {exc.error}")
            sys.exit(1)
        click.echo(f"  OK transcript_file_id={transcript_file_id}")

        click.echo(f"[4/4] fetch transcription for {transcript_file_id} ...")
        try:
            transcription = client.fetch_transcription(transcript_file_id)
        except SlackApiError as exc:
            click.echo(f"  FAIL: {exc.error}")
            sys.exit(1)
        line_count = len(transcription.get("lines") or [])
        if line_count == 0:
            click.echo("  WARN transcription returned 0 lines.")
        else:
            click.echo(f"  OK {line_count} transcript lines.")
        click.echo("\nsmoke-test: OK")


@cli.command()
def status() -> None:
    """Per-workspace token presence and last auth.test result."""
    workspaces = keychain.list_workspaces()
    if not workspaces:
        click.echo("No workspaces configured. Run `slack-huddle-mcp setup`.")
        return
    for ws in workspaces:
        try:
            tokens = keychain.load_tokens(ws)
        except Exception as exc:
            click.echo(f"{ws}: MISSING_TOKENS ({exc})")
            continue
        with SlackHuddleClient(
            xoxc_token=tokens.xoxc,
            xoxd_cookie=tokens.xoxd,
            workspace_subdomain=ws,
        ) as client:
            try:
                info = client.auth_test()
                click.echo(
                    f"{ws}: OK team={info.get('team', '?')} user_id={info.get('user_id', '?')}"
                )
            except AuthError as exc:
                click.echo(f"{ws}: AUTH_FAILED ({exc.error}) — run `setup` again.")
            except SlackApiError as exc:
                click.echo(f"{ws}: ERROR ({exc.error})")


def _resolve_to_canvas(client: SlackHuddleClient, ident: str) -> str:
    if ident.startswith("H"):
        for huddle in client.huddles_history(limit=200):
            if huddle.get("id") == ident:
                canvas_id = huddle.get("transcript_file_id")
                if isinstance(canvas_id, str) and canvas_id:
                    return canvas_id
                raise click.ClickException(f"huddle {ident} has no canvas id")
        raise click.ClickException(f"huddle {ident} not found in recent history")
    return ident


def _resolve_to_transcript_file(client: SlackHuddleClient, ident: str) -> str:
    if ident.startswith("F"):
        return ident
    canvas_id = _resolve_to_canvas(client, ident)
    return client.resolve_transcript_file_id(canvas_id)


def _iso(ts: Any) -> str:
    if not isinstance(ts, (int, float)):
        return ""
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError):
        return ""


def _duration_min(huddle: dict[str, Any]) -> int:
    start = huddle.get("date_start")
    end = huddle.get("date_end")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return 0
    return max(0, int(round((float(end) - float(start)) / 60.0)))


def _auth_help(exc: AuthError) -> str:
    return (
        f"auth failed: {exc.error}. xoxc tokens rotate when you log out of Slack — "
        "run `slack-huddle-mcp setup` again to refresh."
    )


def _mcp_config_snippet() -> str:
    return (
        '{\n'
        '  "mcpServers": {\n'
        '    "slack-huddle": {\n'
        '      "command": "slack-huddle-mcp",\n'
        '      "args": ["serve"]\n'
        '    }\n'
        '  }\n'
        '}\n'
        '\n'
        '# Or, if installed via pipx/uv:\n'
        '# command: "uvx", args: ["slack-huddle-mcp", "serve"]\n'
    )


@cli.command()
def serve() -> None:
    """Run the FastMCP server over stdio (use this from your MCP client config)."""
    from slack_huddle.mcp_server import main as _main

    _main()


if __name__ == "__main__":
    cli()

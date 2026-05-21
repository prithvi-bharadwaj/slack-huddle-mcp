"""CLI commands for browsing huddles: ``list``, ``get``, ``smoke-test``, ``status``."""

from __future__ import annotations

import json
import logging
import sys

import click

from slack_huddle import keychain
from slack_huddle._cli_helpers import (
    auth_help,
    duration_min,
    iso_short,
    open_client,
)
from slack_huddle.api import AuthError, SlackApiError, SlackHuddleClient
from slack_huddle.parser import (
    extract_summary_from_canvas,
    format_lines,
    format_markdown,
    parse_transcription,
)

logger = logging.getLogger(__name__)


def _resolve_to_canvas(client: SlackHuddleClient, ident: str) -> str:
    # File IDs (canvas / transcript) start with F. Everything else (H, R, ...)
    # is treated as a huddle ID and looked up in huddles.history.
    if ident.startswith("F"):
        return ident
    for huddle in client.huddles_history(limit=200):
        if huddle.get("id") == ident:
            canvas_id = huddle.get("transcript_file_id")
            if isinstance(canvas_id, str) and canvas_id:
                return canvas_id
            raise click.ClickException(
                f"huddle {ident} has no canvas yet (Slack typically generates "
                "the AI summary within a few minutes after the huddle ends)"
            )
    raise click.ClickException(f"huddle {ident} not found in recent history")


def _resolve_to_transcript_file(client: SlackHuddleClient, ident: str) -> str:
    if ident.startswith("F"):
        return ident
    canvas_id = _resolve_to_canvas(client, ident)
    return client.resolve_transcript_file_id(canvas_id)


@click.command(name="list")
@click.option("--workspace", "-w", help="Workspace subdomain.")
@click.option("--channel", "-c", help="Channel ID to filter on.")
@click.option("--limit", "-n", default=20, type=int, help="Maximum huddles to show.")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON instead of a table.")
def list_cmd(workspace: str | None, channel: str | None, limit: int, as_json: bool) -> None:
    """List recent huddles."""
    with open_client(workspace) as client:
        try:
            huddles = client.huddles_history(channel_id=channel, limit=limit)
        except AuthError as exc:
            raise click.ClickException(auth_help(exc)) from exc
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
        when = iso_short(huddle.get("date_start"))
        duration = duration_min(huddle)
        channels = huddle.get("channels") or []
        channel_id = channels[0] if channels and isinstance(channels[0], str) else ""
        click.echo(
            f"{huddle.get('id', ''):<24} {when:<25} {duration:>5}  {channel_id}"
        )


@click.command(name="get")
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

    Accepts either a huddle ID (``H0...``) or a transcript file ID (``F0...``).
    """
    with open_client(workspace) as client:
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
            raise click.ClickException(auth_help(exc)) from exc
        except SlackApiError as exc:
            raise click.ClickException(f"slack error: {exc.error}") from exc


@click.command(name="smoke-test")
@click.option("--workspace", "-w", help="Workspace subdomain.")
def smoke_test_cmd(workspace: str | None) -> None:
    """End-to-end check: list -> resolve canvas -> fetch transcription on the latest huddle."""
    with open_client(workspace) as client:
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
            huddles = client.huddles_history(limit=10)
        except SlackApiError as exc:
            click.echo(f"  FAIL: {exc.error}")
            sys.exit(1)
        if not huddles:
            click.echo("  WARN no huddles found; cannot complete transcript check.")
            sys.exit(0)
        click.echo(f"  OK {len(huddles)} huddles; first={huddles[0].get('id', '?')}")

        # Recent huddles may not have an AI canvas yet (Slack generates it
        # asynchronously). Walk forward until we find one that does.
        target_index = None
        canvas_id = ""
        for i, h in enumerate(huddles):
            cid = h.get("transcript_file_id")
            if isinstance(cid, str) and cid:
                target_index = i
                canvas_id = cid
                break

        if target_index is None:
            click.echo(
                f"  WARN none of the {len(huddles)} recent huddles have a canvas "
                "yet (Slack hasn't generated the AI summary). Wait a few minutes "
                "and re-run, or test against an older huddle."
            )
            sys.exit(0)

        if target_index > 0:
            click.echo(
                f"  (skipped {target_index} recent huddle(s) without an AI "
                f"canvas; testing {huddles[target_index].get('id', '?')})"
            )

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


@click.command()
def status() -> None:
    """Per-workspace token presence and last auth.test result."""
    workspaces = keychain.list_workspaces()
    if not workspaces:
        click.echo("No workspaces configured. Run `slack-huddle-mcp setup`.")
        return
    for ws in workspaces:
        try:
            tokens = keychain.load_tokens(ws)
        except Exception as exc:  # noqa: BLE001 — surface any keychain quirk to the user
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

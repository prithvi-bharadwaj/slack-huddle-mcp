"""CLI commands for token entry: ``setup`` and ``bookmarklet``."""

from __future__ import annotations

import logging

import click

from slack_huddle import bookmarklet as bookmarklet_mod
from slack_huddle import keychain
from slack_huddle._cli_helpers import mask, mcp_config_snippet
from slack_huddle.api import AuthError, SlackApiError
from slack_huddle.extractor import ExtractorError, extract_tokens
from slack_huddle.workspace import resolve_workspace

logger = logging.getLogger(__name__)


@click.command()
@click.option("--workspace", "-w", help="Workspace subdomain (e.g. myteam).")
@click.option("--xoxc", help="xoxc token (skip prompt).")
@click.option("--xoxd", help="xoxd cookie value (skip prompt).")
@click.option(
    "--auto",
    is_flag=True,
    help="Auto-extract from the macOS Slack desktop app (no browser).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="With --auto: extract and validate, but do not store tokens.",
)
def setup(
    workspace: str | None,
    xoxc: str | None,
    xoxd: str | None,
    auto: bool,
    dry_run: bool,
) -> None:
    """Walk through token extraction and save to the OS keychain.

    Three modes:
      * Manual (default): paste tokens you got from DevTools.
      * --auto: read directly from the macOS Slack desktop app.
      * --xoxc/--xoxd: skip the prompts entirely (e.g. from the bookmarklet).
    """
    if dry_run and not auto:
        raise click.ClickException("--dry-run requires --auto")

    if auto:
        if xoxc or xoxd:
            raise click.ClickException("--auto cannot be combined with --xoxc/--xoxd")
        click.echo("Auto-extract: reading from the Slack desktop app ...", err=True)
        try:
            tokens = extract_tokens()
        except ExtractorError as exc:
            raise click.ClickException(str(exc)) from exc
        xoxc, xoxd = tokens.xoxc, tokens.xoxd
        click.echo(
            f"Auto-extract: got xoxc ({mask(xoxc)}) and xoxd ({mask(xoxd)}).",
            err=True,
        )
    else:
        click.echo(
            "\n"
            "Slack-huddle-mcp setup\n"
            "----------------------\n"
            "Two tokens come out of the Slack web client. They live in your\n"
            "browser only — Slack does not expose them programmatically.\n"
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
        if not xoxd:
            click.echo(
                "\nStep 2: in DevTools open Application -> Cookies -> https://app.slack.com\n"
                "Find the cookie named `d` (HttpOnly). Copy its raw value (do not URL-decode).\n"
            )
            xoxd = click.prompt("Paste xoxd cookie value", type=str, hide_input=True).strip()

    if not xoxc or not xoxc.startswith("xoxc-"):
        raise click.ClickException("token does not look like an xoxc- token")
    if not xoxd:
        raise click.ClickException("xoxd cookie is required")

    click.echo("Validating tokens via auth.test ...", err=True)
    try:
        info = resolve_workspace(xoxc, xoxd, hint=workspace)
    except AuthError as exc:
        raise click.ClickException(f"auth failed: {exc.error}") from exc
    except SlackApiError as exc:
        raise click.ClickException(f"workspace resolution failed: {exc.error}") from exc

    if dry_run:
        click.echo(
            f"\nDry run: would store tokens for workspace '{info.subdomain}' "
            f"(team={info.team_name or info.team_id}, user_id={info.user_id}).\n"
            "Re-run without --dry-run to persist."
        )
        return

    keychain.store_tokens(info.subdomain, xoxc, xoxd)
    click.echo(
        f"\nStored tokens for workspace '{info.subdomain}' "
        f"(team={info.team_name or info.team_id})."
    )
    click.echo("\nMCP config snippet:\n")
    click.echo(mcp_config_snippet())


@click.command()
@click.option(
    "--print-only",
    is_flag=True,
    help="Print the bookmarklet javascript: URL instead of opening the helper page.",
)
@click.option(
    "--no-open",
    is_flag=True,
    help="Write the helper HTML page but don't open it in the browser.",
)
def bookmarklet(print_only: bool, no_open: bool) -> None:
    """Generate the browser bookmarklet helper for one-click token extraction."""
    if print_only:
        click.echo(bookmarklet_mod.bookmarklet_url())
        return

    if no_open:
        path = bookmarklet_mod.write_helper_page()
    else:
        path = bookmarklet_mod.open_helper_in_browser()

    click.echo(f"Helper page: {path}", err=True)
    if not no_open:
        click.echo(
            "Opened in your default browser — drag the link to your bookmarks bar.",
            err=True,
        )

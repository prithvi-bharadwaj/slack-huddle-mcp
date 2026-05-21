"""Helpers shared across the CLI command modules.

Kept private (underscore-prefixed) — not part of the public surface.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from typing import Any

import click

from slack_huddle import keychain
from slack_huddle.api import AuthError, SlackHuddleClient

logger = logging.getLogger(__name__)


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def resolve_workspace_name(workspace: str | None) -> str:
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


def open_client(workspace: str | None) -> SlackHuddleClient:
    ws = resolve_workspace_name(workspace)
    tokens = keychain.load_tokens(ws)
    return SlackHuddleClient(
        xoxc_token=tokens.xoxc,
        xoxd_cookie=tokens.xoxd,
        workspace_subdomain=ws,
    )


def auth_help(exc: AuthError) -> str:
    return (
        f"auth failed: {exc.error}. xoxc tokens rotate when you log out of Slack — "
        "run `slack-huddle-mcp setup` again to refresh."
    )


def mcp_config_snippet() -> str:
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


def mask(token: str) -> str:
    """First 8 + last 4 chars of a token, with length annotation."""
    if len(token) <= 14:
        return "*" * len(token)
    return f"{token[:8]}...{token[-4:]} ({len(token)} chars)"


def iso_short(ts: Any) -> str:
    if not isinstance(ts, (int, float)):
        return ""
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError):
        return ""


def duration_min(huddle: dict[str, Any]) -> int:
    start = huddle.get("date_start")
    end = huddle.get("date_end")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return 0
    return max(0, int(round((float(end) - float(start)) / 60.0)))

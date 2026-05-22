"""Click CLI entrypoint.

The actual commands live in ``cli_setup`` (token entry) and ``cli_huddles``
(huddle browsing). This module wires them onto a single ``cli`` group so
``slack-huddle-mcp <command>`` keeps working.
"""

from __future__ import annotations

import click

from slack_huddle._cli_helpers import configure_logging
from slack_huddle.cli_huddles import get_cmd, list_cmd, smoke_test_cmd, status
from slack_huddle.cli_setup import bookmarklet, setup


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable DEBUG logging on stderr.")
@click.version_option(package_name="slack-huddle-mcp")
def cli(verbose: bool) -> None:
    """Expose Slack AI huddle transcripts via MCP."""
    configure_logging(verbose)


@cli.command()
@click.option(
    "--http",
    "use_http",
    is_flag=True,
    help="Serve over streamable HTTP (for claude.ai/Cowork via a public tunnel).",
)
@click.option("--host", default="127.0.0.1", help="HTTP bind host (default 127.0.0.1).")
@click.option("--port", default=8765, type=int, help="HTTP bind port (default 8765).")
@click.option(
    "--auth-token",
    envvar="MCP_AUTH_TOKEN",
    default=None,
    help="Secret URL token for HTTP mode. Auto-generated if not set. "
    "Also reads from MCP_AUTH_TOKEN env var.",
)
def serve(
    use_http: bool, host: str, port: int, auth_token: str | None
) -> None:
    """Run the FastMCP server.

    Default: stdio transport (for Claude Code / Claude Desktop, configured via
    ``claude mcp add``).

    With ``--http``: streamable HTTP transport at ``<host>:<port>/mcp/<token>``.
    Combine with a tunnel (ngrok/cloudflared) to make it reachable from
    Claude.ai's cloud for use as a Cowork custom connector.

    The token is part of the URL — requests to any other path return 404. Set
    ``MCP_AUTH_TOKEN`` or pass ``--auth-token`` to make it stable across
    restarts; otherwise a fresh one is generated each run.
    """
    from slack_huddle.mcp_server import main as _main

    if not use_http:
        _main()
        return

    import secrets

    if not auth_token:
        auth_token = secrets.token_urlsafe(32)
        click.echo(
            f"⚠ No --auth-token / MCP_AUTH_TOKEN set; generated one for this run:\n"
            f"    {auth_token}\n"
            f"  Set MCP_AUTH_TOKEN=... to keep the URL stable across restarts.",
            err=True,
        )

    http_path = f"/mcp/{auth_token}"
    click.echo(
        f"\nLocal URL:  http://{host}:{port}{http_path}\n"
        f"Public URL: https://<your-tunnel>{http_path}\n"
        f"            (replace <your-tunnel> with your ngrok / cloudflared host)\n"
        f"            Paste the Public URL into Cowork → Settings → Connectors.\n",
        err=True,
    )
    _main(transport="http", host=host, port=port, http_path=http_path)


cli.add_command(setup)
cli.add_command(bookmarklet)
cli.add_command(list_cmd)
cli.add_command(get_cmd)
cli.add_command(smoke_test_cmd)
cli.add_command(status)


if __name__ == "__main__":
    cli()

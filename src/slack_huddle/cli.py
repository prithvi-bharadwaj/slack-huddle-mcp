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
def serve(use_http: bool, host: str, port: int) -> None:
    """Run the FastMCP server.

    Default: stdio transport (for Claude Code / Claude Desktop, configured via
    ``claude mcp add``).

    With ``--http``: streamable HTTP transport on ``<host>:<port>/mcp``. Combine
    with a tunnel (cloudflared/ngrok) to make it reachable from Claude.ai's
    cloud for use as a Cowork custom connector. WARNING: no built-in auth in
    this mode — keep the tunnel URL private and don't leave it running.
    """
    from slack_huddle.mcp_server import main as _main

    if use_http:
        _main(transport="http", host=host, port=port)
    else:
        _main()


cli.add_command(setup)
cli.add_command(bookmarklet)
cli.add_command(list_cmd)
cli.add_command(get_cmd)
cli.add_command(smoke_test_cmd)
cli.add_command(status)


if __name__ == "__main__":
    cli()

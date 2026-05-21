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
def serve() -> None:
    """Run the FastMCP server over stdio (use this from your MCP client config)."""
    from slack_huddle.mcp_server import main as _main

    _main()


cli.add_command(setup)
cli.add_command(bookmarklet)
cli.add_command(list_cmd)
cli.add_command(get_cmd)
cli.add_command(smoke_test_cmd)
cli.add_command(status)


if __name__ == "__main__":
    cli()

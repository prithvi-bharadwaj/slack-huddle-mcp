# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-05-22

### Added
- `slack-huddle-mcp serve --http` — streamable HTTP transport, for use with
  Claude.ai web / Claude Cowork via a public tunnel (ngrok/cloudflared).
- Path-based bearer-token auth: server listens at ``/mcp/<token>`` only;
  everything else returns 404. Token is read from ``--auth-token`` or
  ``MCP_AUTH_TOKEN`` env var, or auto-generated for the current run.
- README now documents three setup paths (Code, Desktop/Cursor, Cowork)
  and includes a self-contained agent prompt that automates the Cowork
  setup end-to-end.

## [0.2.0] - 2026-05-17

### Added
- `slack-huddle-mcp setup --auto` — extract `xoxc` from the macOS Slack desktop
  app's Local Storage LevelDB and decrypt `xoxd` from its Cookies SQLite via
  the macOS Keychain. Zero browser steps.
- `slack-huddle-mcp setup --auto --dry-run` — extract and validate without
  storing.
- `slack-huddle-mcp bookmarklet` — generate a one-click browser bookmarklet
  helper page; drag a link to the bookmarks bar, click on `app.slack.com`,
  paste the result into the terminal.
- Global `-v` / `--verbose` flag for DEBUG-level logging on stderr.
- `cryptography` is now an explicit dependency (used for cookie decryption).

## [0.1.0] - 2026-05-16

### Added
- Initial release.
- Three-step pipeline that fetches Slack huddle transcripts via `huddles.history` + `files.info`.
- FastMCP server exposing four tools: `list_huddles`, `get_huddle_transcript`,
  `get_huddle_summary`, `list_workspaces`.
- Click CLI: `setup`, `list`, `get`, `smoke-test`, `status`.
- OS-keychain token storage (`keyring`) — never on disk.
- Markdown / JSON / lines transcript formats with consecutive-speaker merging.
- Multi-workspace support resolved via `auth.test`.
- Anonymized fixtures and `respx`-based unit tests, ≥80% coverage on `api.py` and `parser.py`.

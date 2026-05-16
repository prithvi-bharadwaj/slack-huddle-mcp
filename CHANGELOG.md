# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

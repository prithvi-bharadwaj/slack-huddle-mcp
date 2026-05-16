"""OS-keychain storage for Slack workspace tokens.

Tokens are stored via the ``keyring`` library, which delegates to:
- macOS Keychain
- Linux libsecret / KWallet
- Windows Credential Manager

Service: ``slack-huddle-mcp``
Accounts: ``{workspace_subdomain}.xoxc`` and ``{workspace_subdomain}.xoxd``
A separate ``__workspaces__`` index entry tracks which workspaces have stored tokens
(some keyring backends can't enumerate accounts).
"""

from __future__ import annotations

from dataclasses import dataclass

import keyring

SERVICE_NAME = "slack-huddle-mcp"
_INDEX_ACCOUNT = "__workspaces__"
_SEPARATOR = ","


class KeychainError(RuntimeError):
    """Raised when keychain operations fail or required tokens are missing."""


@dataclass(frozen=True, slots=True)
class WorkspaceTokens:
    """Tokens for a single Slack workspace."""

    workspace: str
    xoxc: str
    xoxd: str


def store_tokens(workspace: str, xoxc: str, xoxd: str) -> None:
    """Persist ``xoxc`` and ``xoxd`` for ``workspace`` to the OS keychain."""
    workspace = _normalize_workspace(workspace)
    if not xoxc.startswith("xoxc-"):
        raise KeychainError("xoxc must start with 'xoxc-'")
    if not xoxd:
        raise KeychainError("xoxd is required")
    keyring.set_password(SERVICE_NAME, f"{workspace}.xoxc", xoxc)
    keyring.set_password(SERVICE_NAME, f"{workspace}.xoxd", xoxd)
    _register_workspace(workspace)


def load_tokens(workspace: str) -> WorkspaceTokens:
    """Load the tokens for ``workspace``. Raises ``KeychainError`` if missing."""
    workspace = _normalize_workspace(workspace)
    xoxc = keyring.get_password(SERVICE_NAME, f"{workspace}.xoxc")
    xoxd = keyring.get_password(SERVICE_NAME, f"{workspace}.xoxd")
    if not xoxc or not xoxd:
        raise KeychainError(
            f"no tokens found for workspace '{workspace}'. "
            "Run `slack-huddle-mcp setup` first."
        )
    return WorkspaceTokens(workspace=workspace, xoxc=xoxc, xoxd=xoxd)


def delete_tokens(workspace: str) -> None:
    """Remove stored tokens for ``workspace``."""
    workspace = _normalize_workspace(workspace)
    for suffix in ("xoxc", "xoxd"):
        try:
            keyring.delete_password(SERVICE_NAME, f"{workspace}.{suffix}")
        except keyring.errors.PasswordDeleteError:
            pass
    _deregister_workspace(workspace)


def list_workspaces() -> list[str]:
    """Return all workspaces with stored tokens."""
    index = keyring.get_password(SERVICE_NAME, _INDEX_ACCOUNT) or ""
    workspaces = [w.strip() for w in index.split(_SEPARATOR) if w.strip()]
    return sorted(set(workspaces))


def default_workspace() -> str | None:
    """If exactly one workspace is registered, return it. Otherwise ``None``."""
    workspaces = list_workspaces()
    return workspaces[0] if len(workspaces) == 1 else None


def _normalize_workspace(workspace: str) -> str:
    if not workspace:
        raise KeychainError("workspace name is required")
    return workspace.strip().lower()


def _register_workspace(workspace: str) -> None:
    workspaces = set(list_workspaces())
    workspaces.add(workspace)
    keyring.set_password(SERVICE_NAME, _INDEX_ACCOUNT, _SEPARATOR.join(sorted(workspaces)))


def _deregister_workspace(workspace: str) -> None:
    workspaces = set(list_workspaces())
    workspaces.discard(workspace)
    if workspaces:
        keyring.set_password(SERVICE_NAME, _INDEX_ACCOUNT, _SEPARATOR.join(sorted(workspaces)))
    else:
        try:
            keyring.delete_password(SERVICE_NAME, _INDEX_ACCOUNT)
        except keyring.errors.PasswordDeleteError:
            pass

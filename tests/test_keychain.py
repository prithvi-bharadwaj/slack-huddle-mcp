"""Tests for slack_huddle.keychain with an in-memory keyring backend."""

from __future__ import annotations

from typing import Any

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from slack_huddle import keychain as kc


class InMemoryKeyring(KeyringBackend):
    """Test double — keyring API in a dict."""

    priority = 1000  # type: ignore[assignment]

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self._store:
            raise PasswordDeleteError("not found")
        del self._store[(service, username)]


@pytest.fixture(autouse=True)
def in_memory_keyring() -> Any:
    backend = InMemoryKeyring()
    previous = keyring.get_keyring()
    keyring.set_keyring(backend)
    try:
        yield backend
    finally:
        keyring.set_keyring(previous)


def test_store_and_load_roundtrip() -> None:
    kc.store_tokens("example", "xoxc-1-1-1-secret", "xoxd-cookie-value")
    tokens = kc.load_tokens("example")
    assert tokens.workspace == "example"
    assert tokens.xoxc == "xoxc-1-1-1-secret"
    assert tokens.xoxd == "xoxd-cookie-value"


def test_load_tokens_missing_raises() -> None:
    with pytest.raises(kc.KeychainError):
        kc.load_tokens("unknown")


def test_store_tokens_rejects_bad_xoxc() -> None:
    with pytest.raises(kc.KeychainError):
        kc.store_tokens("example", "not-an-xoxc", "xoxd")


def test_store_tokens_rejects_blank_xoxd() -> None:
    with pytest.raises(kc.KeychainError):
        kc.store_tokens("example", "xoxc-x", "")


def test_store_tokens_rejects_blank_workspace() -> None:
    with pytest.raises(kc.KeychainError):
        kc.store_tokens("", "xoxc-x", "xoxd")


def test_workspace_is_lowercased() -> None:
    kc.store_tokens("Example", "xoxc-x", "xoxd")
    assert kc.list_workspaces() == ["example"]
    assert kc.load_tokens("EXAMPLE").workspace == "example"


def test_list_workspaces_returns_sorted_unique() -> None:
    kc.store_tokens("bravo", "xoxc-x", "xoxd")
    kc.store_tokens("alpha", "xoxc-x", "xoxd")
    kc.store_tokens("alpha", "xoxc-x", "xoxd")
    assert kc.list_workspaces() == ["alpha", "bravo"]


def test_default_workspace_when_one() -> None:
    kc.store_tokens("only", "xoxc-x", "xoxd")
    assert kc.default_workspace() == "only"


def test_default_workspace_when_multiple() -> None:
    kc.store_tokens("a", "xoxc-x", "xoxd")
    kc.store_tokens("b", "xoxc-x", "xoxd")
    assert kc.default_workspace() is None


def test_default_workspace_when_empty() -> None:
    assert kc.default_workspace() is None


def test_delete_tokens_clears_index() -> None:
    kc.store_tokens("example", "xoxc-x", "xoxd")
    kc.delete_tokens("example")
    assert kc.list_workspaces() == []
    with pytest.raises(kc.KeychainError):
        kc.load_tokens("example")


def test_delete_unknown_workspace_is_noop() -> None:
    kc.delete_tokens("not-there")
    assert kc.list_workspaces() == []

"""Tests for slack_huddle.extractor."""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from slack_huddle import extractor
from slack_huddle.extractor import (
    AES_IV,
    KEY_LENGTH,
    PBKDF2_ITERATIONS_MAC,
    PBKDF2_SALT,
    XOXC_PATTERN,
    ExtractedTokens,
    ExtractorError,
    _decrypt_chromium_cookie,
    _extract_xoxc,
    extract_tokens,
)

SAMPLE_XOXC = "xoxc-1111111111-2222222222-3333333333-abc123def4567890abc123def4567890"


def _encrypt_chromium_cookie(plaintext: str, passphrase: str) -> bytes:
    """Replicate Chromium's v10 encryption so we can round-trip the decryptor."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA1(),
        length=KEY_LENGTH,
        salt=PBKDF2_SALT,
        iterations=PBKDF2_ITERATIONS_MAC,
    )
    key = kdf.derive(passphrase.encode("utf-8"))

    data = plaintext.encode("utf-8")
    pad_len = 16 - (len(data) % 16)
    padded = data + bytes([pad_len] * pad_len)

    cipher = Cipher(algorithms.AES(key), modes.CBC(AES_IV))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return b"v10" + ciphertext


def _build_fake_app(
    tmp_path: Path,
    *,
    leveldb_contents: bytes | None = b"random junk " + SAMPLE_XOXC.encode() + b" more junk",
    cookie_value: bytes | None = b"v10-placeholder",
    include_cookie: bool = True,
) -> Path:
    """Create a fake ``~/Library/Application Support/Slack`` tree."""
    app_dir = tmp_path / "Slack"
    leveldb_dir = app_dir / "Local Storage" / "leveldb"
    leveldb_dir.mkdir(parents=True)
    if leveldb_contents is not None:
        (leveldb_dir / "000003.log").write_bytes(leveldb_contents)
        (leveldb_dir / "MANIFEST-000001").write_bytes(b"manifest data")

    if include_cookie:
        cookies_db = app_dir / "Cookies"
        conn = sqlite3.connect(cookies_db)
        try:
            conn.execute(
                "CREATE TABLE cookies (host_key TEXT, name TEXT, encrypted_value BLOB)"
            )
            conn.execute(
                "INSERT INTO cookies VALUES (?, ?, ?)",
                (".slack.com", "d", cookie_value),
            )
            conn.commit()
        finally:
            conn.close()
    return app_dir


# ---------------------------------------------------------------------------
# regex coverage
# ---------------------------------------------------------------------------


def test_xoxc_pattern_matches_canonical_format() -> None:
    blob = b"prefix " + SAMPLE_XOXC.encode() + b" suffix"
    matches = XOXC_PATTERN.findall(blob)
    assert matches == [SAMPLE_XOXC.encode()]


def test_xoxc_pattern_ignores_other_xox_tokens() -> None:
    blob = b"xoxb-bot-token xoxs-something xoxp-personal"
    assert XOXC_PATTERN.findall(blob) == []


# ---------------------------------------------------------------------------
# decryption round-trip
# ---------------------------------------------------------------------------


def test_decrypt_chromium_cookie_roundtrip() -> None:
    plaintext = "xoxd-test-cookie-value=="
    passphrase = "supersecret"
    encrypted = _encrypt_chromium_cookie(plaintext, passphrase)
    assert _decrypt_chromium_cookie(encrypted, passphrase) == plaintext


def test_decrypt_returns_plain_when_not_v10() -> None:
    assert _decrypt_chromium_cookie(b"plain-cookie-value", "anything") == "plain-cookie-value"


def test_decrypt_rejects_bad_ciphertext_length() -> None:
    with pytest.raises(ExtractorError, match="ciphertext length"):
        _decrypt_chromium_cookie(b"v10" + b"abc", "x")


def test_decrypt_rejects_bad_padding() -> None:
    # Valid 16-byte ciphertext block but wrong key -> garbage padding.
    encrypted = _encrypt_chromium_cookie("hi", "right-passphrase")
    with pytest.raises(ExtractorError):
        _decrypt_chromium_cookie(encrypted, "wrong-passphrase")


# ---------------------------------------------------------------------------
# xoxc extraction
# ---------------------------------------------------------------------------


def test_extract_xoxc_from_leveldb(tmp_path: Path) -> None:
    app_dir = _build_fake_app(tmp_path)
    assert _extract_xoxc(app_dir) == SAMPLE_XOXC


def test_extract_xoxc_picks_most_frequent_when_multiple(tmp_path: Path) -> None:
    other = "xoxc-9999999999-8888888888-7777777777-deadbeef1234567890deadbeef123456"
    blob = (SAMPLE_XOXC + " " + SAMPLE_XOXC + " " + other).encode()
    app_dir = _build_fake_app(tmp_path, leveldb_contents=blob)
    assert _extract_xoxc(app_dir) == SAMPLE_XOXC


def test_extract_xoxc_raises_when_no_tokens(tmp_path: Path) -> None:
    app_dir = _build_fake_app(tmp_path, leveldb_contents=b"nothing matching here")
    with pytest.raises(ExtractorError, match="no xoxc token"):
        _extract_xoxc(app_dir)


def test_extract_xoxc_raises_without_leveldb_dir(tmp_path: Path) -> None:
    app_dir = tmp_path / "EmptySlack"
    app_dir.mkdir()
    with pytest.raises(ExtractorError, match="local storage not found"):
        _extract_xoxc(app_dir)


# ---------------------------------------------------------------------------
# full extract_tokens flow (with mocked Keychain)
# ---------------------------------------------------------------------------


def test_extract_tokens_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(extractor.platform, "system", lambda: "Darwin")

    passphrase = "round-trip-passphrase"
    encrypted = _encrypt_chromium_cookie("xoxd-roundtrip-cookie==", passphrase)
    app_dir = _build_fake_app(tmp_path, cookie_value=encrypted)

    def fake_keychain() -> str:
        return passphrase

    monkeypatch.setattr(extractor, "_read_keychain_passphrase", fake_keychain)

    result = extract_tokens(app_dir=app_dir)
    assert isinstance(result, ExtractedTokens)
    assert result.xoxc == SAMPLE_XOXC
    assert result.xoxd == "xoxd-roundtrip-cookie=="


def test_extract_tokens_rejects_non_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extractor.platform, "system", lambda: "Linux")
    with pytest.raises(ExtractorError, match="macOS only"):
        extract_tokens()


def test_extract_tokens_missing_app_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(extractor.platform, "system", lambda: "Darwin")
    missing = tmp_path / "does-not-exist"
    with pytest.raises(ExtractorError, match="not found"):
        extract_tokens(app_dir=missing)


# ---------------------------------------------------------------------------
# keychain shell-out
# ---------------------------------------------------------------------------


def test_read_keychain_tries_both_services(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    class FakeCompleted:
        stdout = "secret-from-app-store\n"

    def fake_run(cmd: list[str], **_: Any) -> FakeCompleted:
        calls.append(cmd)
        # Fail on first service, succeed on second.
        if "Slack Safe Storage" in cmd:
            raise subprocess.CalledProcessError(1, cmd)
        return FakeCompleted()

    monkeypatch.setattr(extractor.subprocess, "run", fake_run)
    result = extractor._read_keychain_passphrase()
    assert result == "secret-from-app-store"
    assert len(calls) == 2


def test_read_keychain_raises_when_all_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **_: Any) -> None:
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(extractor.subprocess, "run", fake_run)
    with pytest.raises(ExtractorError, match="keychain passphrase"):
        extractor._read_keychain_passphrase()

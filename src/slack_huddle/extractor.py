"""Auto-extract Slack tokens from the Slack desktop app (macOS only for now).

xoxc: regex-search through ``Local Storage/leveldb`` files. The token format
      (``xoxc-{team}-{user}-{session}-{secret}``) is distinctive enough that a
      direct binary regex over the leveldb files is reliable without parsing
      the leveldb log/ldb format.

xoxd: read the encrypted ``d`` cookie from ``Cookies`` (SQLite), then decrypt
      it via the Chromium-derived scheme (PBKDF2-SHA1, AES-128-CBC, ``v10``
      prefix). The PBKDF2 passphrase lives in the macOS Keychain under
      ``Slack Safe Storage`` (or ``Slack App Store Safe Storage`` for the
      Mac App Store build).
"""

from __future__ import annotations

import logging
import platform
import re
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

XOXC_PATTERN = re.compile(rb"xoxc-[0-9]+-[0-9]+-[0-9]+-[a-fA-F0-9]+")
PBKDF2_SALT = b"saltysalt"
PBKDF2_ITERATIONS_MAC = 1003
KEY_LENGTH = 16
AES_IV = b" " * 16

# Order matters — direct download first, then Mac App Store fallback.
KEYCHAIN_SERVICES = ("Slack Safe Storage", "Slack App Store Safe Storage")


class ExtractorError(RuntimeError):
    """Raised when auto-extraction fails."""


@dataclass(frozen=True, slots=True)
class ExtractedTokens:
    xoxc: str
    xoxd: str


def slack_app_dir() -> Path:
    """Return the Slack desktop app data directory on macOS."""
    return Path.home() / "Library" / "Application Support" / "Slack"


def extract_tokens(app_dir: Path | None = None) -> ExtractedTokens:
    """Pull ``xoxc`` + ``xoxd`` from the Slack desktop app.

    Raises ``ExtractorError`` with a remediation-oriented message on every
    failure. Logs INFO progress so the user sees what's happening.
    """
    logger.info("auto-extract: starting")
    if platform.system() != "Darwin":
        raise ExtractorError(
            f"auto-extract supports macOS only (this is {platform.system()}). "
            "Use `slack-huddle-mcp setup` for manual entry, or "
            "`slack-huddle-mcp bookmarklet` for a browser helper."
        )

    if app_dir is None:
        app_dir = slack_app_dir()
    logger.info("auto-extract: looking in %s", app_dir)

    if not app_dir.exists():
        raise ExtractorError(
            f"Slack desktop app data not found at {app_dir}. "
            "Install Slack for macOS and log in, or use `slack-huddle-mcp setup` "
            "for manual entry."
        )

    xoxc = _extract_xoxc(app_dir)
    logger.info("auto-extract: xoxc found (%d chars)", len(xoxc))

    xoxd = _extract_xoxd(app_dir)
    logger.info("auto-extract: xoxd decrypted (%d chars)", len(xoxd))

    return ExtractedTokens(xoxc=xoxc, xoxd=xoxd)


def _extract_xoxc(app_dir: Path) -> str:
    leveldb_dir = app_dir / "Local Storage" / "leveldb"
    if not leveldb_dir.exists():
        raise ExtractorError(f"Slack local storage not found at {leveldb_dir}")

    logger.debug("auto-extract: scanning %s for xoxc tokens", leveldb_dir)
    candidates: list[str] = []
    files_scanned = 0
    for path in sorted(leveldb_dir.iterdir()):
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            logger.debug("auto-extract: skipping %s (%s)", path.name, exc)
            continue
        files_scanned += 1
        for match in XOXC_PATTERN.finditer(data):
            candidates.append(match.group(0).decode("ascii"))

    logger.debug(
        "auto-extract: scanned %d files, found %d xoxc candidates",
        files_scanned,
        len(candidates),
    )

    if not candidates:
        raise ExtractorError(
            "no xoxc token found in Slack local storage. "
            "Open the Slack desktop app and log in first, then retry."
        )

    unique = sorted(set(candidates))
    if len(unique) > 1:
        logger.warning(
            "auto-extract: %d distinct xoxc tokens found (multiple workspaces). "
            "Picking the most-frequent. Pass --workspace to validate after.",
            len(unique),
        )
    # Most-frequent (and longest, as tiebreaker) candidate.
    return max(unique, key=lambda t: (candidates.count(t), len(t)))


def _extract_xoxd(app_dir: Path) -> str:
    cookies_db = app_dir / "Cookies"
    if not cookies_db.exists():
        raise ExtractorError(f"Slack cookies db not found at {cookies_db}")

    logger.debug("auto-extract: reading 'd' cookie from %s", cookies_db)
    encrypted = _read_d_cookie(cookies_db)
    logger.debug("auto-extract: encrypted 'd' cookie is %d bytes", len(encrypted))

    passphrase = _read_keychain_passphrase()
    logger.debug("auto-extract: got keychain passphrase (%d chars)", len(passphrase))

    return _decrypt_chromium_cookie(encrypted, passphrase)


def _read_d_cookie(cookies_db: Path) -> bytes:
    uri = f"file:{cookies_db}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        cur = conn.execute(
            "SELECT encrypted_value FROM cookies "
            "WHERE host_key LIKE '%.slack.com' AND name = 'd'"
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if not row or not row[0]:
        raise ExtractorError(
            "no 'd' cookie found in Slack cookies db. "
            "Log into Slack via the desktop app first."
        )
    return bytes(row[0])


def _read_keychain_passphrase() -> str:
    last_error: subprocess.CalledProcessError | None = None
    for service in KEYCHAIN_SERVICES:
        logger.debug("auto-extract: trying keychain service %r", service)
        try:
            result = subprocess.run(
                ["security", "find-generic-password", "-s", service, "-w"],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            last_error = exc
            continue
        return result.stdout.strip()
    raise ExtractorError(
        "could not read Slack keychain passphrase. "
        "If macOS prompted you to allow access, click 'Always Allow' and retry. "
        f"Tried services: {', '.join(KEYCHAIN_SERVICES)}"
    ) from last_error


def _decrypt_chromium_cookie(encrypted: bytes, passphrase: str) -> str:
    if not encrypted.startswith(b"v10"):
        try:
            return encrypted.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ExtractorError("cookie is not v10-encrypted and not utf-8") from exc

    ciphertext = encrypted[3:]
    if len(ciphertext) == 0 or len(ciphertext) % 16 != 0:
        raise ExtractorError(
            f"unexpected cookie ciphertext length: {len(ciphertext)} bytes"
        )

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA1(),
        length=KEY_LENGTH,
        salt=PBKDF2_SALT,
        iterations=PBKDF2_ITERATIONS_MAC,
    )
    key = kdf.derive(passphrase.encode("utf-8"))

    cipher = Cipher(algorithms.AES(key), modes.CBC(AES_IV))
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()

    pad_len = padded[-1]
    if pad_len < 1 or pad_len > 16:
        raise ExtractorError(f"invalid PKCS7 pad length: {pad_len}")
    plaintext = padded[:-pad_len]

    # Older Chromium: plaintext == cookie_value directly.
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError:
        pass

    # Newer Chromium (and recent Electron) binds the cookie to its domain by
    # prefixing the plaintext with a host-derived value (hash/MAC) before
    # encrypting. Slack's `d` cookie value always starts with `xoxd-`; scan
    # for that marker and return from there.
    for marker in (b"xoxd-", b"xoxs-"):
        idx = plaintext.find(marker)
        if idx >= 0:
            logger.debug(
                "auto-extract: stripped %d-byte domain-bind prefix before %s",
                idx,
                marker.decode(),
            )
            try:
                return plaintext[idx:].decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ExtractorError(
                    f"found {marker.decode()} marker but tail isn't utf-8"
                ) from exc

    raise ExtractorError(
        "decrypted cookie is not valid utf-8 and no xoxd-/xoxs- marker found. "
        f"first 16 bytes (hex): {plaintext[:16].hex()}"
    )

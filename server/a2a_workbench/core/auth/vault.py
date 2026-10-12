"""Authenticated encryption of stored credentials."""

import base64
import binascii
import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from a2a_workbench.core.config import Settings

_NONCE = 12


class VaultError(Exception):
    """Raised when a key is unusable or a ciphertext cannot be decrypted."""


class Vault:
    """Encrypts JSON-serializable dicts with AES-256-GCM under one key."""

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise VaultError("vault key must be 32 bytes")
        self._aead = AESGCM(key)

    def encrypt(self, value: dict[str, Any]) -> bytes:
        """Return ``nonce || ciphertext`` of ``value`` serialized as JSON."""
        nonce = os.urandom(_NONCE)
        return nonce + self._aead.encrypt(nonce, json.dumps(value).encode(), None)

    def decrypt(self, blob: bytes) -> dict[str, Any]:
        """Return the dict encrypted in ``blob``.

        Raises:
            VaultError: if ``blob`` was not produced by this key or was altered.
        """
        try:
            plain = self._aead.decrypt(blob[:_NONCE], blob[_NONCE:], None)
        except (InvalidTag, ValueError) as exc:
            raise VaultError("credential cannot be decrypted with the current key") from exc
        value = json.loads(plain)
        if not isinstance(value, dict):
            raise VaultError("credential payload is not an object")
        return value


def load_vault_key(settings: Settings) -> bytes:
    """Return the vault key from ``settings.secret_key`` (base64) or ``<home>/secret.key``.

    The key file is created with mode 0600 when missing; concurrent callers
    on a fresh home all get the same key.

    Raises:
        VaultError: if the configured key is not 32 bytes of base64.
    """
    if settings.secret_key:
        try:
            key = base64.b64decode(settings.secret_key, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise VaultError("A2AW_SECRET_KEY is not valid base64") from exc
        if len(key) != 32:
            raise VaultError("A2AW_SECRET_KEY must decode to 32 bytes")
        return key
    path = settings.home / "secret.key"
    if not path.exists():
        _create_key_file(path)
    key = base64.b64decode(path.read_text().strip())
    if len(key) != 32:
        raise VaultError(f"{path} does not hold a 32-byte key")
    return key


def _create_key_file(path: Path) -> None:
    # Write the whole key to a private temp file, then hard-link it into place:
    # the link appears atomically and complete, and when another process wins
    # the race its key is kept and read instead.
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".secret.key.")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(base64.b64encode(os.urandom(32)).decode())
        os.chmod(tmp, 0o600)
        with contextlib.suppress(FileExistsError):
            os.link(tmp, path)
    finally:
        os.unlink(tmp)

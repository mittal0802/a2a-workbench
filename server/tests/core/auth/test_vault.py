import base64
import os
import stat

import pytest

from a2a_workbench.core.auth.vault import Vault, VaultError, load_vault_key
from a2a_workbench.core.config import Settings


def test_round_trip_and_tamper_detection():
    vault = Vault(os.urandom(32))
    blob = vault.encrypt({"token": "s3cret"})
    assert b"s3cret" not in blob
    assert vault.decrypt(blob) == {"token": "s3cret"}
    with pytest.raises(VaultError):
        vault.decrypt(blob[:-1] + bytes([blob[-1] ^ 1]))


def test_wrong_key_fails():
    blob = Vault(os.urandom(32)).encrypt({"a": 1})
    with pytest.raises(VaultError):
        Vault(os.urandom(32)).decrypt(blob)


def test_key_file_is_created_private_and_stable(tmp_path, monkeypatch):
    monkeypatch.delenv("A2AW_SECRET_KEY", raising=False)
    settings = Settings(home=tmp_path)
    key = load_vault_key(settings)
    path = tmp_path / "secret.key"
    assert len(key) == 32 and path.exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_vault_key(settings) == key


def test_key_from_environment(tmp_path, monkeypatch):
    raw = os.urandom(32)
    monkeypatch.setenv("A2AW_SECRET_KEY", base64.b64encode(raw).decode())
    assert load_vault_key(Settings(home=tmp_path)) == raw
    assert not (tmp_path / "secret.key").exists()


def test_bad_environment_key_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("A2AW_SECRET_KEY", "short")
    with pytest.raises(VaultError):
        load_vault_key(Settings(home=tmp_path))

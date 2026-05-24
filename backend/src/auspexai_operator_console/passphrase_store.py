"""Operator passphrase store — dual-backend (Secret Service + encrypted file).

Follows the worker keystore pattern (auspexai_worker.keystore): prefers
Secret Service (GNOME Keyring / KWallet) when a D-Bus session is available,
falls back to a ChaCha20-Poly1305-encrypted file keyed to machine-id + UID.

The CLI `set-passphrase` command writes the passphrase; the running service
reads it at login-time for the rage-shell second-factor check.
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
from pathlib import Path
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class PassphraseStoreError(Exception):
    pass


class PassphraseNotFoundError(PassphraseStoreError):
    pass


@runtime_checkable
class PassphraseStore(Protocol):
    def has_passphrase(self) -> bool: ...
    def store(self, passphrase: str) -> None: ...
    def load(self) -> str: ...
    def delete(self) -> None: ...
    def backend_name(self) -> str: ...


def verify(store: PassphraseStore, candidate: str) -> bool:
    """Constant-time comparison of candidate against stored passphrase."""
    try:
        stored = store.load()
    except PassphraseNotFoundError:
        return False
    return hmac.compare_digest(stored.encode(), candidate.encode())


# ---------------------------------------------------------------------------
# Secret Service backend
# ---------------------------------------------------------------------------

_SS_SCHEMA = {
    "service": "auspexai-operator-console",
    "key-type": "operator-passphrase",
}
_SS_LABEL = "AuspexAI operator console — operator passphrase"


class SecretServicePassphraseStore:
    """Stores operator passphrase in GNOME Keyring / Secret Service."""

    def __init__(self) -> None:
        try:
            import secretstorage  # type: ignore[import-not-found]
        except ImportError as exc:
            raise PassphraseStoreError(
                "SecretStorage is not installed; install with the [secret-service] extra"
            ) from exc
        self._ss = secretstorage
        try:
            self._conn = secretstorage.dbus_init()
            self._coll = secretstorage.get_default_collection(self._conn)
            if self._coll.is_locked():
                self._coll.unlock()
        except Exception as exc:
            raise PassphraseStoreError(
                f"could not connect to Secret Service: {exc}"
            ) from exc

    def _find(self):
        items = list(self._coll.search_items(_SS_SCHEMA))
        return items[0] if items else None

    def has_passphrase(self) -> bool:
        return self._find() is not None

    def store(self, passphrase: str) -> None:
        self._coll.create_item(
            _SS_LABEL, _SS_SCHEMA, passphrase.encode(), replace=True,
        )

    def load(self) -> str:
        item = self._find()
        if item is None:
            raise PassphraseNotFoundError("no operator passphrase in Secret Service")
        return item.get_secret().decode()

    def delete(self) -> None:
        item = self._find()
        if item is not None:
            item.delete()

    def backend_name(self) -> str:
        return "Secret Service (GNOME Keyring)"


# ---------------------------------------------------------------------------
# Encrypted-file backend (same pattern as auspexai_worker.keystore)
# ---------------------------------------------------------------------------

_MAGIC = b"AOPv"  # AuspexAI operator passphrase
_VERSION = 0x01
_NONCE_LEN = 12
_KDF_INFO = b"auspexai-operator-console-passphrase-v0"


def _read_machine_id() -> str:
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            content = Path(path).read_text(encoding="ascii").strip()
        except FileNotFoundError:
            continue
        if content:
            return content
    raise PassphraseStoreError(
        "no machine-id found at /etc/machine-id or /var/lib/dbus/machine-id"
    )


def _derive_key(machine_id: str, uid: int) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=_KDF_INFO,
    ).derive(f"{machine_id}:{uid}".encode())


class EncryptedFilePassphraseStore:
    """Stores operator passphrase in a ChaCha20-Poly1305-encrypted file."""

    def __init__(
        self,
        path: Path,
        *,
        machine_id: str | None = None,
        uid: int | None = None,
    ) -> None:
        self._path = path
        self._machine_id = machine_id if machine_id is not None else _read_machine_id()
        self._uid = uid if uid is not None else os.geteuid()

    def has_passphrase(self) -> bool:
        return self._path.exists()

    def store(self, passphrase: str) -> None:
        from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        nonce = secrets.token_bytes(_NONCE_LEN)
        cipher = ChaCha20Poly1305(_derive_key(self._machine_id, self._uid))
        ct = cipher.encrypt(nonce, passphrase.encode(), associated_data=_MAGIC)
        payload = _MAGIC + bytes([_VERSION]) + nonce + ct
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_bytes(payload)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self._path)

    def load(self) -> str:
        from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

        if not self.has_passphrase():
            raise PassphraseNotFoundError(f"no passphrase file at {self._path}")
        data = self._path.read_bytes()
        min_len = len(_MAGIC) + 1 + _NONCE_LEN + 16
        if len(data) < min_len:
            raise PassphraseStoreError(f"passphrase file at {self._path} is too short")
        if data[: len(_MAGIC)] != _MAGIC:
            raise PassphraseStoreError(f"passphrase file at {self._path} has wrong magic")
        if data[len(_MAGIC)] != _VERSION:
            raise PassphraseStoreError("unsupported passphrase file version")
        offset = len(_MAGIC) + 1
        nonce = data[offset : offset + _NONCE_LEN]
        ct = data[offset + _NONCE_LEN :]
        cipher = ChaCha20Poly1305(_derive_key(self._machine_id, self._uid))
        try:
            plaintext = cipher.decrypt(nonce, ct, associated_data=_MAGIC)
        except Exception as exc:
            raise PassphraseStoreError(
                f"failed to decrypt passphrase at {self._path}; machine-id or uid "
                "may have changed since the passphrase was stored"
            ) from exc
        return plaintext.decode()

    def delete(self) -> None:
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass

    def backend_name(self) -> str:
        return f"encrypted file ({self._path})"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def _try_secret_service(timeout: float = 3.0) -> SecretServicePassphraseStore | None:
    """Probe for Secret Service with a timeout to avoid D-Bus hangs."""
    import threading

    result: list[SecretServicePassphraseStore | None] = [None]

    def probe() -> None:
        try:
            result[0] = SecretServicePassphraseStore()
        except (PassphraseStoreError, ImportError, Exception):
            pass

    t = threading.Thread(target=probe, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        logger.warning(
            "Secret Service probe timed out after %.1fs; using encrypted file", timeout,
        )
        return None
    return result[0]


def default_store(*, encrypted_file_path: Path) -> PassphraseStore:
    """Return the best available passphrase store for this host.

    Prefers Secret Service when reachable (desktop session with D-Bus);
    falls back to encrypted file (headless / systemd without D-Bus session).
    """
    encrypted = EncryptedFilePassphraseStore(encrypted_file_path)
    ss = _try_secret_service()
    if ss is not None:
        if ss.has_passphrase():
            return ss
        if not encrypted.has_passphrase():
            return ss
    return encrypted

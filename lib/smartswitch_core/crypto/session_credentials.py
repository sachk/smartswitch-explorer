from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import string
import xml.etree.ElementTree as ET

from Crypto.Cipher import AES

from smartswitch_core.crypto.common import DEFAULT_DUMMY_HEX


_WINDOWS_HISTORY_KEY = b"0b1e96db05d64ea4"
_AES_BLOCK_BYTES = 16
_MAX_METADATA_BYTES = 16 * 1024 * 1024


class SessionCredentialError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SessionCredential:
    value: str = field(repr=False)
    source: str
    security_level: str | None = None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _read_limited(path: Path) -> bytes:
    size = path.stat().st_size
    if size > _MAX_METADATA_BYTES:
        raise SessionCredentialError("Smart Switch credential metadata is unexpectedly large")
    return path.read_bytes()


def _validate_dummy(raw: bytes) -> str:
    raw = raw.rstrip(b"\x00")
    try:
        value = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise SessionCredentialError("Decrypted Smart Switch Dummy is not ASCII") from exc

    if not 32 <= len(value) <= 128 or len(value) % 2:
        raise SessionCredentialError("Decrypted Smart Switch Dummy has an invalid length")
    if any(char not in string.hexdigits for char in value):
        raise SessionCredentialError("Decrypted Smart Switch Dummy is not hexadecimal")
    return value


def decrypt_windows_backup_history_dummy(path: Path) -> str:
    """Recover the session Dummy stored by Smart Switch for Windows.

    The metadata value is AES-128-ECB encrypted and zero padded. The returned
    credential is deliberately never included in exception messages or reprs.
    """

    try:
        root = ET.fromstring(_read_limited(path))
    except (OSError, ET.ParseError) as exc:
        raise SessionCredentialError("Unable to parse Smart Switch credential metadata") from exc

    values = [
        (element.text or "").strip()
        for element in root.iter()
        if _local_name(element.tag) == "Dummy" and (element.text or "").strip()
    ]
    if len(values) != 1:
        raise SessionCredentialError("Smart Switch credential metadata must contain one Dummy value")

    encoded = values[0]
    if len(encoded) % 2 or any(char not in string.hexdigits for char in encoded):
        raise SessionCredentialError("Encrypted Smart Switch Dummy is not valid hexadecimal")
    ciphertext = bytes.fromhex(encoded)
    if not ciphertext or len(ciphertext) % _AES_BLOCK_BYTES:
        raise SessionCredentialError("Encrypted Smart Switch Dummy is not AES block-aligned")

    plaintext = AES.new(_WINDOWS_HISTORY_KEY, AES.MODE_ECB).decrypt(ciphertext)
    return _validate_dummy(plaintext)


def _read_security_level(backup_dir: Path) -> str | None:
    path = backup_dir / "ReqItemsInfo.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(_read_limited(path))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    value = data.get("SecurityLevel") if isinstance(data, dict) else None
    return value if isinstance(value, str) else None


def load_session_credential(backup_dir: Path) -> SessionCredential:
    history_path = backup_dir / "backupHistoryInfo.xml"
    if not history_path.is_file():
        raise SessionCredentialError("Smart Switch backupHistoryInfo.xml was not found")
    return SessionCredential(
        value=decrypt_windows_backup_history_dummy(history_path),
        source="backupHistoryInfo.xml (Windows session Dummy)",
        security_level=_read_security_level(backup_dir),
    )


def credential_candidates(
    backup_dir: Path,
    explicit_credential: str | None = None,
    *,
    include_legacy_default: bool = True,
) -> list[SessionCredential]:
    candidates: list[SessionCredential] = []
    if explicit_credential is not None:
        candidates.append(SessionCredential(explicit_credential, "explicit credential"))
    try:
        candidates.append(load_session_credential(backup_dir))
    except SessionCredentialError:
        pass
    if include_legacy_default:
        candidates.append(SessionCredential(DEFAULT_DUMMY_HEX, "legacy project default"))

    deduplicated: list[SessionCredential] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.value in seen:
            continue
        seen.add(candidate.value)
        deduplicated.append(candidate)
    return deduplicated

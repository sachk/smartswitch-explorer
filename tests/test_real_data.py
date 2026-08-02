from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from smartswitch_core.applications.android_backup import (
    inspect_android_backup_file,
)
from smartswitch_core.applications.decrypt_extract import _decrypt_penc
from smartswitch_core.crypto.common import DEFAULT_DUMMY_HEX
from smartswitch_core.crypto.session_credentials import SessionCredentialError, load_session_credential


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _real_data_path() -> Path:
    raw_path = os.environ.get("SMARTSWITCH_REAL_DATA")
    if not raw_path:
        pytest.skip("SMARTSWITCH_REAL_DATA is not set")
    path = Path(raw_path)
    assert path.is_file()
    return path


def _real_credentials(path: Path) -> list[str]:
    candidates: list[str] = []
    password = os.environ.get("SMARTSWITCH_REAL_DATA_PASSWORD")
    if password:
        candidates.append(password)
    try:
        candidates.append(load_session_credential(path.parent.parent).value)
    except SessionCredentialError:
        pass
    if not candidates:
        pytest.fail(
            "No authenticated real-backup test is possible: provide backupHistoryInfo.xml "
            "beside APKFILE or set SMARTSWITCH_REAL_DATA_PASSWORD"
        )
    return candidates


@pytest.mark.real_backup
def test_real_data_authenticates_with_backup_session_credential() -> None:
    path = _real_data_path()
    before = _sha256(path)
    inspection = inspect_android_backup_file(path, credential_candidates=_real_credentials(path))
    after = _sha256(path)

    assert before == after
    assert inspection.magic == "ANDROID BACKUP"
    assert inspection.phase == "ok"
    assert inspection.message == "Decoded payload is authenticated and TAR-valid"
    assert inspection.tar_entries is not None
    assert inspection.tar_entries > 0


@pytest.mark.real_backup
def test_real_penc_authenticates_with_backup_session_credential() -> None:
    data_path = _real_data_path()
    penc_path = data_path.with_suffix(".penc")
    if not penc_path.is_file():
        pytest.skip("The matching .penc file is not present")

    credential = load_session_credential(data_path.parent.parent).value
    before = _sha256(penc_path)
    apk = _decrypt_penc(penc_path, credential)
    after = _sha256(penc_path)

    assert before == after
    assert apk.startswith(b"PK\x03\x04")
    if credential != DEFAULT_DUMMY_HEX:
        with pytest.raises(ValueError):
            _decrypt_penc(penc_path, DEFAULT_DUMMY_HEX)

from __future__ import annotations

import os
from pathlib import Path

import pytest

from smartswitch_core.applications.android_backup import (
    UNAVAILABLE_CREDENTIAL_MESSAGE,
    inspect_android_backup_file,
)
from smartswitch_core.crypto.common import DEFAULT_DUMMY_HEX


@pytest.mark.real_backup
def test_real_data_file_diagnostic_from_environment() -> None:
    raw_path = os.environ.get("SMARTSWITCH_REAL_DATA")
    if not raw_path:
        pytest.skip("SMARTSWITCH_REAL_DATA is not set")

    path = Path(raw_path)
    assert path.is_file()

    candidates = [DEFAULT_DUMMY_HEX]
    password = os.environ.get("SMARTSWITCH_REAL_DATA_PASSWORD")
    if password:
        candidates.insert(0, password)

    before = path.read_bytes()
    inspection = inspect_android_backup_file(path, credential_candidates=candidates)
    after = path.read_bytes()

    assert before == after
    assert inspection.magic == "ANDROID BACKUP"
    assert inspection.phase in {
        "ok",
        "master-key padding failure",
        "master-key checksum mismatch",
        "malformed master-key structure",
    }
    if inspection.phase == "ok":
        assert inspection.tar_entries is not None
    else:
        assert inspection.message == UNAVAILABLE_CREDENTIAL_MESSAGE

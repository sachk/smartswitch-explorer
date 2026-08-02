from __future__ import annotations

import json
from pathlib import Path

import pytest

from smartswitch_core.export import make_export_root, write_manifest
from smartswitch_core.path_safety import safe_output_path


def test_make_export_root(tmp_path: Path) -> None:
    out = make_export_root(tmp_path, "SM-F946B_20260201210657")
    assert out.exists()
    assert out.name == "SM-F946B_20260201210657"


@pytest.mark.parametrize(
    "unsafe",
    [
        "../outside.txt",
        "/absolute.txt",
        r"C:\Users\Example Person\file.txt",
        r"C:drive-relative.txt",
        r"\\server\share\file.txt",
    ],
)
def test_safe_output_path_rejects_unsafe_paths(tmp_path: Path, unsafe: str) -> None:
    with pytest.raises(ValueError):
        safe_output_path(tmp_path / "output", unsafe)


def test_safe_output_path_rejects_existing_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "output"
    outside = tmp_path / "output-private"
    root.mkdir()
    outside.mkdir()
    link = root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlinks are unavailable: {exc}")

    with pytest.raises(ValueError):
        safe_output_path(root, "linked/secret.txt")


def test_write_manifest_redacts_absolute_paths_recursively(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    write_manifest(
        manifest_path,
        {
            "source": tmp_path / "backup with spaces",
            "warnings": [
                f"Failed at {tmp_path / 'backup with spaces' / 'file.data'}",
                r"Failed at C:\Users\Example Person\Backup\file.data",
                r"Failed at \\server\share\Example Person\file.data",
            ],
        },
    )

    raw = manifest_path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    assert str(tmp_path) not in raw
    assert "Example Person" not in raw
    assert payload["source"] == "<path>"
    assert all("<path>" in warning for warning in payload["warnings"])

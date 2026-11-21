from __future__ import annotations

import io
import os
import tarfile
from pathlib import Path

import pytest

from smartswitch_core.applications.decrypt_extract import _safe_extract_tar
from smartswitch_core.path_safety import (
    SafeOutputPaths,
    safe_output_path,
    sanitize_windows_component,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("frc_1:2314:android:abc.json", "frc_1_2314_android_abc.json"),
        ("a<b>c", "a_b_c"),
        ("a?b", "a_b"),
        ("a|b", "a_b"),
        ("a\x00b", "a_b"),
        ("a\nb", "a_b"),
        ("name.", "name"),
        ("name ", "name"),
        ("name. ", "name"),
        ("...", "_"),
        ("CON", "_CON"),
        ("con.txt", "_con.txt"),
        ("PRN", "_PRN"),
        ("AUX.log", "_AUX.log"),
        ("NUL", "_NUL"),
        ("COM1.log", "_COM1.log"),
        ("LPT9", "_LPT9"),
    ],
)
def test_sanitize_windows_component(raw: str, expected: str) -> None:
    assert sanitize_windows_component(raw) == expected


@pytest.mark.skipif(os.name == "nt", reason="Windows sanitizes names by default")
def test_default_keeps_valid_posix_name(tmp_path: Path) -> None:
    path = safe_output_path(tmp_path, "frc_1:2314:android:abc.json")
    assert path.name == "frc_1:2314:android:abc.json"


def test_sanitization_does_not_bypass_validation(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        safe_output_path(
            tmp_path,
            "../outside.txt",
            sanitize_windows_names=True,
        )


def test_colliding_file_names_are_disambiguated(tmp_path: Path) -> None:
    paths = SafeOutputPaths(tmp_path / "out", sanitize_windows_names=True)

    first = paths.path_for("frc_1:one.txt")
    second = paths.path_for("frc_1?one.txt")

    assert first.name == "frc_1_one.txt"
    assert second.name == "frc_1_one~2.txt"
    assert paths.mapping == {
        "frc_1:one.txt": "frc_1_one.txt",
        "frc_1?one.txt": "frc_1_one~2.txt",
    }


def test_colliding_directories_keep_children_separate(tmp_path: Path) -> None:
    paths = SafeOutputPaths(tmp_path / "out", sanitize_windows_names=True)

    first_dir = paths.path_for("frc_1:dir", is_directory=True)
    first_file = paths.path_for("frc_1:dir/one.txt")
    second_dir = paths.path_for("frc_1?dir", is_directory=True)
    second_file = paths.path_for("frc_1?dir/two.txt")

    assert first_dir == first_file.parent
    assert second_dir == second_file.parent
    assert first_dir != second_dir
    assert second_dir.name == "frc_1_dir~2"


def test_file_then_directory_collision_is_disambiguated(tmp_path: Path) -> None:
    paths = SafeOutputPaths(tmp_path / "out", sanitize_windows_names=True)

    file_path = paths.path_for("frc_1_one.txt")
    directory_path = paths.path_for("frc_1:one.txt", is_directory=True)

    assert file_path.name == "frc_1_one.txt"
    assert directory_path.name == "frc_1_one~2.txt"


def test_windows_collisions_ignore_case(tmp_path: Path) -> None:
    paths = SafeOutputPaths(tmp_path / "out", sanitize_windows_names=True)

    paths.path_for("Readme.txt")
    second = paths.path_for("README.txt")

    assert second.name == "README~2.txt"


def test_windows_path_is_stable_when_requested_twice(tmp_path: Path) -> None:
    paths = SafeOutputPaths(tmp_path / "out", sanitize_windows_names=True)

    first = paths.path_for("frc_1:dir/file.txt")
    second = paths.path_for("frc_1:dir/file.txt")

    assert first == second


def test_directory_path_is_reused_by_children(tmp_path: Path) -> None:
    paths = SafeOutputPaths(tmp_path / "out", sanitize_windows_names=True)

    directory = paths.path_for("frc_1:dir", is_directory=True)
    child = paths.path_for("frc_1:dir/file.txt")

    assert child.parent == directory
    assert paths.mapping == {
        "frc_1:dir": "frc_1_dir",
        "frc_1:dir/file.txt": "frc_1_dir/file.txt",
    }


def test_unchanged_name_is_not_recorded(tmp_path: Path) -> None:
    paths = SafeOutputPaths(tmp_path / "out", sanitize_windows_names=True)

    paths.path_for("plain.txt")

    assert paths.mapping == {}


@pytest.mark.skipif(os.name != "nt", reason="requires Windows file name rules")
def test_extract_tar_with_windows_invalid_names(tmp_path: Path) -> None:
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w") as archive:
        directory = tarfile.TarInfo(".com.google.firebase:example")
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)

        content = b'{"enabled": true}'
        member = tarfile.TarInfo(
            ".com.google.firebase:example/frc_1:2314:android:abc.json"
        )
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))

    tar_path = tmp_path / "app-data.tar"
    tar_path.write_bytes(payload.getvalue())
    out_dir = tmp_path / "out"

    extracted, warnings, renamed = _safe_extract_tar(tar_path, out_dir)

    assert extracted == 1
    assert warnings == []
    assert (
        out_dir
        / ".com.google.firebase_example"
        / "frc_1_2314_android_abc.json"
    ).read_bytes() == content
    assert renamed == {
        ".com.google.firebase:example": ".com.google.firebase_example",
        ".com.google.firebase:example/frc_1:2314:android:abc.json": (
            ".com.google.firebase_example/frc_1_2314_android_abc.json"
        ),
    }

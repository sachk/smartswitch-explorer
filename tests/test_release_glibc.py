from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


CHECKER = Path(__file__).resolve().parents[1] / "scripts/release/check_glibc.py"


def run_checker(bundle: Path, maximum: str = "2.35", **environment: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), "--max-version", maximum, str(bundle)],
        capture_output=True,
        text=True,
        env={**os.environ, **environment},
        check=False,
    )


@pytest.fixture
def elf_factory(tmp_path: Path):
    if not sys.platform.startswith("linux"):
        pytest.skip("ELF release checking is Linux-specific")
    compiler = shutil.which("cc")
    if compiler is None or shutil.which("readelf") is None:
        pytest.skip("ELF fixtures require a C compiler and binutils")
    source = tmp_path / "provider.c"
    source.write_text("void fixture_symbol(void) {}\n", encoding="utf-8")
    consumer = tmp_path / "consumer.c"
    consumer.write_text(
        "extern void fixture_symbol(void);\nvoid use_symbol(void) { fixture_symbol(); }\n",
        encoding="utf-8",
    )
    counter = 0

    def create(destination: Path, version: str, *, needs: bool = True) -> Path:
        nonlocal counter
        counter += 1
        version_script = tmp_path / f"versions-{counter}.map"
        version_script.write_text(
            f"{version} {{ global: fixture_symbol; local: *; }};\n", encoding="utf-8"
        )
        provider = tmp_path / f"provider-{counter}.so"
        subprocess.run(
            [
                compiler, "-shared", "-fPIC", "-nostdlib", str(source),
                f"-Wl,--version-script={version_script}", f"-Wl,-soname,{provider.name}",
                "-o", str(provider),
            ],
            check=True, capture_output=True, text=True,
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if needs:
            subprocess.run(
                [
                    compiler, "-shared", "-fPIC", "-nostdlib", str(consumer),
                    str(provider), "-o", str(destination),
                ],
                check=True, capture_output=True, text=True,
            )
        else:
            shutil.copyfile(provider, destination)
        return destination

    return create


@pytest.mark.parametrize(
    ("required", "maximum", "status"),
    [("2.35", "2.35", 0), ("2.36", "2.35", 1), ("2.9", "2.35", 0), ("2.35", "2.35.0", 0)],
)
def test_cli_enforces_numeric_glibc_ceiling(tmp_path: Path, elf_factory, required: str, maximum: str, status: int) -> None:
    bundle = tmp_path / "bundle"
    elf_factory(bundle / "nested" / "native.so", f"GLIBC_{required}")
    (bundle / "README.txt").write_text("GLIBC_99.99 is plain text, not ELF\n", encoding="utf-8")

    result = run_checker(bundle, maximum)

    assert result.returncode == status, result.stdout + result.stderr
    assert f"highest GLIBC requirement is {required}" in result.stdout
    assert "nested/native.so" in result.stdout
    if status:
        assert f"above the permitted {maximum}" in result.stdout


def test_cli_reports_all_highest_owners_and_ignores_provided_versions(tmp_path: Path, elf_factory) -> None:
    bundle = tmp_path / "bundle"
    elf_factory(bundle / "older.so", "GLIBC_2.9")
    elf_factory(bundle / "first.so", "GLIBC_2.35")
    elf_factory(bundle / "nested" / "second.so", "GLIBC_2.35")
    elf_factory(bundle / "provider.so", "GLIBC_99.99", needs=False)
    elf_factory(bundle / "cpp.so", "GLIBCXX_3.4.99")

    result = run_checker(bundle)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Inspected 5 ELF files; highest GLIBC requirement is 2.35" in result.stdout
    assert "- first.so" in result.stdout
    assert "- nested/second.so" in result.stdout
    assert "- older.so" not in result.stdout
    assert "- provider.so" not in result.stdout


def test_cli_rejects_elf_without_glibc_requirements(tmp_path: Path, elf_factory) -> None:
    bundle = tmp_path / "bundle"
    elf_factory(bundle / "cpp.so", "GLIBCXX_3.4.99")

    result = run_checker(bundle)

    assert result.returncode == 1
    assert "No GLIBC requirements found in 1 ELF files" in result.stdout


def test_cli_rejects_bundle_without_elf(tmp_path: Path) -> None:
    (tmp_path / "text.txt").write_text("GLIBC_2.35", encoding="utf-8")

    result = run_checker(tmp_path)

    assert result.returncode == 1
    assert "No ELF files found" in result.stdout


def test_cli_rejects_missing_bundle(tmp_path: Path) -> None:
    result = run_checker(tmp_path / "missing")

    assert result.returncode == 2
    assert "Bundle directory does not exist" in result.stderr


@pytest.mark.parametrize("maximum", ["-2.35", "2..35", "2", "2.35junk"])
def test_cli_rejects_invalid_ceiling(tmp_path: Path, maximum: str) -> None:
    result = run_checker(tmp_path, maximum)

    assert result.returncode == 2
    assert "--max-version" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_fails_closed_when_readelf_rejects_elf(tmp_path: Path) -> None:
    if shutil.which("readelf") is None:
        pytest.skip("Requires binutils")
    (tmp_path / "broken.so").write_bytes(b"\x7fELFnot a valid ELF file")

    result = run_checker(tmp_path)

    assert result.returncode == 1
    assert "readelf failed for" in result.stdout
    assert "broken.so" in result.stdout


def test_cli_fails_closed_when_readelf_is_unavailable(tmp_path: Path) -> None:
    (tmp_path / "native.so").write_bytes(b"\x7fELF")

    result = run_checker(tmp_path, PATH=str(tmp_path / "no-tools"))

    assert result.returncode == 1
    assert "readelf" in result.stdout
    assert "Traceback" not in result.stderr

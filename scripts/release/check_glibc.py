#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess


GLIBC_VERSION_PATTERN = re.compile(r"\bGLIBC_(\d+(?:\.\d+)*)\b")


def parse_version(value: str) -> tuple[int, ...]:
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", value):
        raise ValueError(f"Invalid version: {value}")
    parts = [int(part) for part in value.split(".")]
    while parts[-1] == 0 and len(parts) > 2:
        parts.pop()
    return tuple(parts)


def required_glibc_versions(readelf_output: str) -> set[tuple[int, ...]]:
    # Definitions describe versions an ELF provides, not versions it requires.
    # readelf also lists symbol versions; only the needs section is authoritative.
    versions: set[tuple[int, ...]] = set()
    in_needs = False
    for line in readelf_output.splitlines():
        if line.startswith("Version "):
            in_needs = line.startswith("Version needs section ")
        elif in_needs:
            versions.update(
                parse_version(match.group(1))
                for match in GLIBC_VERSION_PATTERN.finditer(line)
            )
    return versions


def _is_elf(path: Path) -> bool:
    with path.open("rb") as stream:
        return stream.read(4) == b"\x7fELF"


def inspect_bundle(root: Path) -> tuple[tuple[int, ...], list[Path], int]:
    highest: tuple[int, ...] = ()
    owners: list[Path] = []
    elf_count = 0

    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        if not _is_elf(path):
            continue
        elf_count += 1
        result = subprocess.run(
            ["readelf", "--wide", "--version-info", str(path)],
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "LC_ALL": "C"},
        )
        if result.returncode != 0:
            raise RuntimeError(f"readelf failed for {path}: {result.stderr.strip()}")
        versions = required_glibc_versions(result.stdout)
        if not versions:
            continue
        candidate = max(versions)
        if candidate > highest:
            highest = candidate
            owners = [path]
        elif candidate == highest:
            owners.append(path)

    return highest, owners, elf_count


def format_version(version: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reject a Linux bundle that requires a newer GLIBC than intended."
    )
    parser.add_argument("bundle", type=Path, help="Directory containing the Linux bundle.")
    parser.add_argument(
        "--max-version", required=True, type=parse_version, help="Highest permitted GLIBC version."
    )
    args = parser.parse_args()

    if not args.bundle.is_dir():
        parser.error(f"Bundle directory does not exist: {args.bundle}")

    permitted = args.max_version
    try:
        highest, owners, elf_count = inspect_bundle(args.bundle)
    except (OSError, RuntimeError) as exc:
        print(f"::error::{exc}")
        return 1
    if elf_count == 0:
        print(f"::error::No ELF files found in {args.bundle}")
        return 1
    if not highest:
        print(f"::error::No GLIBC requirements found in {elf_count} ELF files")
        return 1

    detected = format_version(highest)
    print(f"Inspected {elf_count} ELF files; highest GLIBC requirement is {detected}.")
    for owner in owners:
        print(f"- {owner.relative_to(args.bundle)}")

    if highest > permitted:
        print(
            f"::error::Bundle requires GLIBC {detected}, above the permitted "
            f"{format_version(permitted)}"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

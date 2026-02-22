#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


MIB = 1024 * 1024

SIZE_BUDGETS_BYTES: tuple[tuple[str, int], ...] = (
    ("-windows-x64.exe", 220 * MIB),
    ("-windows-arm64.exe", 190 * MIB),
    ("-macos-universal2.app.zip", 560 * MIB),
    ("-linux-x86_64.AppImage", 190 * MIB),
    ("-linux-aarch64.AppImage", 190 * MIB),
    ("-linux-x86_64.flatpak", 150 * MIB),
    ("-linux-aarch64.flatpak", 150 * MIB),
)


def _format_size(size_bytes: int) -> str:
    return f"{size_bytes / MIB:.1f} MiB"


def _budget_for(path: Path) -> int | None:
    if path.name.endswith(".sha256"):
        return None
    for suffix, budget in SIZE_BUDGETS_BYTES:
        if path.name.endswith(suffix):
            return budget
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Report release artifact sizes and soft budget warnings.")
    parser.add_argument("files", nargs="+", help="Artifact files to inspect.")
    args = parser.parse_args()

    items = [Path(raw) for raw in args.files]
    existing = [path for path in items if path.exists() and path.is_file()]
    if not existing:
        print("No artifact files found.")
        return 0

    print("Artifact sizes:")
    for path in sorted(existing):
        size = path.stat().st_size
        print(f"- {path.name}: {_format_size(size)}")

    warned = False
    for path in sorted(existing):
        budget = _budget_for(path)
        if budget is None:
            continue
        size = path.stat().st_size
        if size <= budget:
            continue
        warned = True
        detail = (
            f"{path.name} is {_format_size(size)} which exceeds budget "
            f"{_format_size(budget)} by {_format_size(size - budget)}"
        )
        print(f"::warning file={path.name}::{detail}")
        print(f"WARNING: {detail}")

    if not warned:
        print("All tracked artifact sizes are within soft budgets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

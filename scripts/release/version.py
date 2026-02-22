#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tomllib


def read_version() -> str:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data.get("project")
    if not isinstance(project, dict):
        raise RuntimeError("pyproject.toml is missing [project]")
    version = project.get("version")
    if not version:
        raise RuntimeError("pyproject.toml is missing project.version")
    return str(version)


def normalize_tag(tag: str) -> str:
    cleaned = tag.strip()
    if cleaned.startswith("refs/tags/"):
        cleaned = cleaned.removeprefix("refs/tags/")
    if cleaned.startswith("v"):
        cleaned = cleaned[1:]
    return cleaned


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check-tag",
        default="",
        help="Validate that the provided tag (vX.Y.Z or refs/tags/vX.Y.Z) matches project.version.",
    )
    args = parser.parse_args()

    version = read_version()

    if args.check_tag:
        tag_version = normalize_tag(args.check_tag)
        if tag_version != version:
            print(
                f"Tag/version mismatch: tag={args.check_tag!r} resolves to {tag_version!r}, "
                f"but pyproject.toml version is {version!r}",
                file=sys.stderr,
            )
            return 1

    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

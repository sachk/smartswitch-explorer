#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from smartswitch_core.applications.android_backup import inspect_android_backup_file
from smartswitch_core.crypto.common import DEFAULT_DUMMY_HEX


def _credential_candidates(args: argparse.Namespace) -> list[str]:
    candidates: list[str] = []
    if args.use_default_credential:
        candidates.append(DEFAULT_DUMMY_HEX)
    if args.try_empty:
        candidates.append("")
    if args.password_env:
        value = os.environ.get(args.password_env)
        if value:
            candidates.append(value)
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return deduped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print non-sensitive diagnostics for a Samsung Smart Switch APKFILE .data file.",
    )
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--password-env",
        default="SMARTSWITCH_DATA_PASSWORD",
        help="Environment variable containing an optional data-file password.",
    )
    parser.add_argument(
        "--try-empty",
        action="store_true",
        help="Also try an empty password candidate without printing it.",
    )
    parser.add_argument(
        "--no-default-credential",
        action="store_false",
        dest="use_default_credential",
        help="Do not try the project's default Smart Switch credential.",
    )
    args = parser.parse_args(argv)

    inspection = inspect_android_backup_file(
        args.path,
        credential_candidates=_credential_candidates(args),
    )
    for key, value in inspection.public_dict().items():
        if value is None:
            continue
        print(f"{key}: {value}")
    return 0 if inspection.phase == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

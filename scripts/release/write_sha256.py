#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path



def write_checksum(path: Path) -> Path:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checksum_path = path.with_suffix(path.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    return checksum_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", help="Files to checksum.")
    args = parser.parse_args()

    for raw in args.files:
        path = Path(raw)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Cannot checksum missing file: {path}")
        out = write_checksum(path)
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

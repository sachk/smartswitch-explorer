#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys


PROFILES: dict[str, dict[str, str | list[str]]] = {
    "windows-exe": {
        "name": "smartswitch-explorer",
        "extra": ["--onefile"],
    },
    "macos-app": {
        "name": "SmartSwitch Explorer",
        "extra": [],
    },
    "linux-dir": {
        "name": "smartswitch-explorer",
        "extra": [],
    },
}


def build(profile: str) -> None:
    if profile not in PROFILES:
        raise RuntimeError(f"Unknown profile: {profile}")

    separator = ";" if os.name == "nt" else ":"
    config = PROFILES[profile]
    name = str(config["name"])
    extra = [str(item) for item in config["extra"]]

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        name,
        "--paths",
        "src",
        "--paths",
        "lib",
        "--collect-all",
        "PySide6",
        "--add-data",
        f"src/gui/assets{separator}gui/assets",
        "--add-data",
        f"src/gui/translations{separator}gui/translations",
        *extra,
        "src/gui/main.py",
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)



def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        required=True,
        choices=sorted(PROFILES.keys()),
        help="PyInstaller build profile.",
    )
    args = parser.parse_args()
    build(args.profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

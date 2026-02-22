#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


QT_EXCLUDED_MODULES: tuple[str, ...] = (
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.QtLocation",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtQml",
    "PySide6.QtQmlCore",
    "PySide6.QtQmlMeta",
    "PySide6.QtQmlModels",
    "PySide6.QtQmlWorkerScript",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickDialogs2",
    "PySide6.QtQuickEffects",
    "PySide6.QtQuickParticles",
    "PySide6.QtQuickShapes",
    "PySide6.QtQuickTest",
    "PySide6.QtQuickTimeline",
    "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialBus",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtStateMachine",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
    "PySide6.QtWebView",
    "PySide6.QtXml",
    "PySide6.QtXmlPatterns",
)

PROFILES: dict[str, dict[str, str | list[str]]] = {
    "windows-exe": {
        "name": "smartswitch-explorer",
        "extra": ["--onefile"],
    },
    "macos-app": {
        "name": "SmartSwitch Explorer",
        "extra": [],
    },
    "macos-universal": {
        "name": "SmartSwitch Explorer",
        "extra": ["--target-architecture", "universal2"],
    },
    "linux-dir": {
        "name": "smartswitch-explorer",
        "extra": ["--strip"],
    },
}


def build(profile: str, upx_dir: str | None = None) -> None:
    if profile not in PROFILES:
        raise RuntimeError(f"Unknown profile: {profile}")

    separator = ";" if os.name == "nt" else ":"
    config = PROFILES[profile]
    name = str(config["name"])
    extra = [str(item) for item in config["extra"]]
    effective_upx_dir = (upx_dir or os.environ.get("UPX_DIR") or "").strip()

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
        "--add-data",
        f"src/gui/assets{separator}gui/assets",
        "--add-data",
        f"src/gui/translations{separator}gui/translations",
    ]
    for module in QT_EXCLUDED_MODULES:
        cmd.extend(["--exclude-module", module])
    if effective_upx_dir:
        upx_path = Path(effective_upx_dir)
        if not upx_path.exists():
            raise RuntimeError(f"UPX directory does not exist: {effective_upx_dir}")
        cmd.extend(["--upx-dir", str(upx_path)])
    cmd.extend([*extra, "src/gui/main.py"])
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
    parser.add_argument(
        "--upx-dir",
        default=None,
        help="Optional directory that contains the upx executable.",
    )
    args = parser.parse_args()
    build(args.profile, upx_dir=args.upx_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

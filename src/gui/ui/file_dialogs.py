from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QWidget


def select_existing_directory(
    parent: QWidget,
    caption: str,
    initial_directory: str = "",
) -> Path | None:
    dialog = QFileDialog(parent, caption, initial_directory)
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
    dialog.setFileMode(QFileDialog.FileMode.Directory)
    dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)

    # Linux desktop portals can ignore Directory mode for AppImages. The Qt
    # dialog keeps folder selection consistent across desktop environments.
    if sys.platform.startswith("linux"):
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)

    if not dialog.exec():
        return None

    selected = dialog.selectedFiles()
    if not selected:
        return None

    path = Path(selected[0]).expanduser()
    if not path.is_dir():
        return None
    return path

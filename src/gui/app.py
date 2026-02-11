from __future__ import annotations

import signal
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from gui.ui.main_window import MainWindow


def run_app() -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName("smartswitch-explorer")
    app.setApplicationName("smartswitch-explorer")
    app.setDesktopFileName("smartswitch-explorer")
    icon_path = Path(__file__).resolve().parent / "assets" / "app_icon.png"
    if icon_path.exists():
        icon = QIcon(str(icon_path))
        app.setWindowIcon(icon)

    window = MainWindow()
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()

    # Keep Python signal handling alive while Qt owns the event loop.
    tick = QTimer()
    tick.setInterval(200)
    tick.timeout.connect(lambda: None)
    tick.start()
    try:
        signal.signal(signal.SIGINT, lambda *_: app.quit())
    except ValueError:
        pass

    exit_code = app.exec()
    tick.stop()
    return exit_code

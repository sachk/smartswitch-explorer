from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from gui.localization import setup_localization
from gui.ui.main_window import MainWindow


def _qt_argv(argv: list[str] | None) -> list[str]:
    if argv:
        return list(argv)
    if argv is not None:
        return [sys.argv[0]]
    return list(sys.argv)


def _configure_application(app: QApplication) -> Path:
    app.setOrganizationName("smartswitch-explorer")
    app.setApplicationName("smartswitch-explorer")
    app.setDesktopFileName("smartswitch-explorer")
    setup_localization(app)
    icon_path = Path(__file__).resolve().parent / "assets" / "app_icon.png"
    if icon_path.exists():
        icon = QIcon(str(icon_path))
        app.setWindowIcon(icon)
    return icon_path


def run_app(argv: list[str] | None = None) -> int:
    app = QApplication(_qt_argv(argv))
    icon_path = _configure_application(app)

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


def run_smoke_test(argv: list[str] | None = None) -> int:
    # Smoke mode runs without entering the main event loop, so packaging CI can
    # verify that Qt and app assets initialize correctly in headless runners.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(_qt_argv(argv))
    _configure_application(app)
    app.processEvents()
    app.quit()
    return 0

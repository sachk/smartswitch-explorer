from __future__ import annotations

from PySide6.QtWidgets import QApplication

from webapp.ui.main_window import MainWindow


def run_app() -> int:
    app = QApplication([])
    window = MainWindow()
    window.show()
    return app.exec()

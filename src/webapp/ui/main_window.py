from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QMainWindow


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SmartSwitch Explorer")
        self.resize(QSize(760, 980))

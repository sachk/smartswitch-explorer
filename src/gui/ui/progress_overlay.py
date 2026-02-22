from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

from gui.localization import tr
from gui.ui.progress_state import EtaEstimator, format_eta_seconds


class ProgressOverlay(QWidget):
    cancel_requested = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("progressOverlay")
        self.setVisible(False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoFillBackground(False)

        self._eta = EtaEstimator(min_visible_seconds=20.0)

        root = QVBoxLayout(self)
        root.setContentsMargins(56, 56, 56, 56)
        root.setSpacing(14)
        root.addStretch(1)

        self.title = QLabel(tr("ProgressOverlay", "Working..."), self)
        self.title.setStyleSheet("font-size: 22px; font-weight: 700;")
        self.title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(self.title)

        self.status = QLabel("", self)
        self.status.setWordWrap(True)
        self.status.setStyleSheet("font-size: 15px;")
        self.status.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(self.status)

        self.progress = QProgressBar(self)
        self.progress.setTextVisible(True)
        self.progress.setRange(0, 0)
        self.progress.setMinimumHeight(34)
        self.progress.setStyleSheet(
            "QProgressBar {"
            "  border: 1px solid palette(mid);"
            "  border-radius: 8px;"
            "  background: palette(base);"
            "  font-size: 14px;"
            "}"
            "QProgressBar::chunk {"
            "  background: palette(highlight);"
            "  border-radius: 7px;"
            "}"
        )
        root.addWidget(self.progress)

        self.numbers = QLabel(tr("ProgressOverlay", "Working..."), self)
        self.numbers.setStyleSheet("font-size: 14px;")
        self.numbers.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(self.numbers)

        self.eta = QLabel("", self)
        self.eta.setStyleSheet("font-size: 14px;")
        self.eta.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.eta.hide()
        root.addWidget(self.eta)

        self.cancel_text = QLabel(self)
        self.cancel_text.setTextFormat(Qt.TextFormat.RichText)
        self.cancel_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.cancel_text.setOpenExternalLinks(False)
        self.cancel_text.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.cancel_text.setStyleSheet("font-size: 15px;")
        self.cancel_text.linkActivated.connect(self._emit_cancel)
        root.addWidget(self.cancel_text)

        root.addStretch(1)

        if parent is not None:
            parent.installEventFilter(self)
        self._sync_geometry()

    def begin(self, title: str, *, cancellable: bool) -> None:
        self._eta.reset()
        self.title.setText(title)
        self.status.setText("")
        self.progress.setRange(0, 0)
        self.numbers.setText(tr("ProgressOverlay", "Working..."))
        self.eta.hide()
        self.cancel_text.setVisible(cancellable)
        self.cancel_text.setText(f"<a href='cancel'>{tr('ProgressOverlay', 'Cancel')}</a>")
        self._sync_geometry()
        self.raise_()
        self.show()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def finish(self) -> None:
        self.hide()
        self._eta.reset()

    def set_status(self, message: str) -> None:
        self.status.setText(message)

    def set_cancel_enabled(self, enabled: bool) -> None:
        if not self.cancel_text.isVisible():
            return
        if enabled:
            self.cancel_text.setText(f"<a href='cancel'>{tr('ProgressOverlay', 'Cancel')}</a>")
        else:
            self.cancel_text.setText(tr("ProgressOverlay", "Cancelling..."))

    def update_progress(self, payload: Mapping[str, object]) -> None:
        phase_label = str(payload.get("phase_label") or "").strip()
        detail = str(payload.get("detail") or "").strip()
        if phase_label and detail:
            self.status.setText(f"{phase_label}: {detail}")
        elif phase_label:
            self.status.setText(phase_label)
        elif detail:
            self.status.setText(detail)

        total_value = payload.get("total")
        current_value = payload.get("current")
        unit = str(payload.get("unit") or "steps")
        indeterminate = bool(payload.get("indeterminate", False))

        if indeterminate or not isinstance(total_value, int) or total_value <= 0:
            self.progress.setRange(0, 0)
            self.numbers.setText(tr("ProgressOverlay", "Working..."))
            self.eta.hide()
            return

        current = current_value if isinstance(current_value, int) else 0
        total = total_value
        current = max(0, min(current, total))

        self.progress.setRange(0, total)
        self.progress.setValue(current)
        self.numbers.setText(f"{current:,} / {total:,} {unit}")

        eta_seconds = self._eta.update(current=current, total=total)
        if eta_seconds is None:
            self.eta.hide()
            return
        self.eta.setText(f"{tr('ProgressOverlay', 'ETA')}: {format_eta_seconds(eta_seconds)}")
        self.eta.show()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        try:
            scrim = self.palette().color(QPalette.ColorRole.Window)
            scrim.setAlpha(184)
            painter.fillRect(self.rect(), scrim)
        finally:
            painter.end()

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if watched is self.parent() and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Move,
            QEvent.Type.Show,
        }:
            self._sync_geometry()
        return super().eventFilter(watched, event)

    def _sync_geometry(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.setGeometry(parent.rect())

    def _emit_cancel(self, _link: str) -> None:
        self.cancel_requested.emit()

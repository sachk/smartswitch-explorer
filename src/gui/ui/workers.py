from __future__ import annotations

import threading
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, Signal


class CancelToken:
    def __init__(self) -> None:
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    progress = Signal(object)
    status = Signal(str)


class FunctionWorker(QRunnable):
    def __init__(
        self,
        fn: Callable[..., Any],
        *args: Any,
        enable_progress: bool = False,
        cancel_token: CancelToken | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.enable_progress = enable_progress
        self.cancel_token = cancel_token
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            call_kwargs = dict(self.kwargs)
            if self.enable_progress:
                call_kwargs.setdefault("progress", self.signals.progress.emit)
                call_kwargs.setdefault("set_status", self.signals.status.emit)
                call_kwargs.setdefault("cancel_token", self.cancel_token)
            result = self.fn(*self.args, **call_kwargs)
            self.signals.result.emit(result)
        except Exception as exc:  # pragma: no cover - worker guard
            tb = traceback.format_exc()
            self.signals.error.emit(f"{exc}\n{tb}")

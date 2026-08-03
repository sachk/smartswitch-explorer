from __future__ import annotations

from gui.ui import landing_page


class _SignalRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def emit(self, *args: object) -> None:
        self.calls.append(args)


class _UnexpectedThreadPool:
    def start(self, _worker: object) -> None:
        raise AssertionError("Refresh without roots must not start a worker")


class _RefreshState:
    def __init__(self) -> None:
        self._refresh_running = False
        self._refresh_pending = False
        self._refresh_worker = None
        self._recent_backup_hints = []
        self._thread_pool = _UnexpectedThreadPool()
        self.listing_started = _SignalRecorder()
        self.results: list[list[landing_page.BackupRowModel]] = []

    def _on_refresh_result(self, rows: list[landing_page.BackupRowModel]) -> None:
        self.results.append(rows)
        self._refresh_running = False


def test_refresh_without_selected_or_discovered_folder_finishes_synchronously(monkeypatch) -> None:
    state = _RefreshState()
    monkeypatch.setattr(landing_page, "discover_backup_roots", lambda: [])

    landing_page.LandingPage.refresh(state)  # type: ignore[arg-type]

    assert state.listing_started.calls == [()]
    assert state.results == [[]]
    assert state._refresh_running is False
    assert state._refresh_worker is None

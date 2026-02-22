from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass


def format_eta_seconds(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    if total < 60:
        return f"~{total}s"

    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"~{minutes}m {secs:02d}s"

    hours, mins = divmod(minutes, 60)
    return f"~{hours}h {mins:02d}m"


@dataclass(frozen=True)
class _Sample:
    at: float
    current: int


class EtaEstimator:
    def __init__(
        self,
        *,
        min_visible_seconds: float = 20.0,
        window_seconds: float = 12.0,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self.min_visible_seconds = min_visible_seconds
        self.window_seconds = window_seconds
        self._now_fn = now_fn or time.monotonic
        self.reset()

    def reset(self) -> None:
        self._started_at = self._now_fn()
        self._samples: deque[_Sample] = deque()
        self._last_total: int | None = None

    def update(self, *, current: int, total: int) -> float | None:
        if total <= 0:
            return None
        if current <= 0:
            return None
        if current >= total:
            return 0.0

        now = self._now_fn()
        elapsed = now - self._started_at
        if elapsed < self.min_visible_seconds:
            return None

        if self._last_total is not None and self._last_total != total:
            self._samples.clear()
        self._last_total = total

        self._samples.append(_Sample(at=now, current=current))
        cutoff = now - self.window_seconds
        while self._samples and self._samples[0].at < cutoff:
            self._samples.popleft()
        if len(self._samples) < 2:
            return None

        first = self._samples[0]
        last = self._samples[-1]
        delta_count = last.current - first.current
        delta_time = last.at - first.at
        if delta_count <= 0 or delta_time <= 0:
            return None

        rate = delta_count / delta_time
        remaining = total - current
        return remaining / rate

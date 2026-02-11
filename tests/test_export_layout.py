from __future__ import annotations

from pathlib import Path

from smartswitch_core.export import make_export_root


def test_make_export_root(tmp_path: Path) -> None:
    out = make_export_root(tmp_path, "SM-F946B_20260201210657")
    assert out.exists()
    assert out.name == "SM-F946B_20260201210657"

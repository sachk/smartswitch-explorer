from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import smartswitch_core.direct_file as direct_file
from smartswitch_core.file_signatures import DirectFileKind


def test_resolve_prefers_ancestor_backup(monkeypatch, tmp_path: Path) -> None:
    backup_a = tmp_path / "A" / "backup_a"
    backup_b = tmp_path / "B" / "backup_b"
    (backup_a / "APKFILE").mkdir(parents=True)
    (backup_b / "APKFILE").mkdir(parents=True)
    source_file = backup_a / "nested" / "sample.data"
    source_file.parent.mkdir(parents=True)
    source_file.write_bytes(b"x")

    def fake_is_backup_dir(path: Path) -> bool:
        return path == backup_a or path == backup_b

    def fake_find_backups(_root: Path) -> list[SimpleNamespace]:
        return [SimpleNamespace(path=backup_a), SimpleNamespace(path=backup_b)]

    monkeypatch.setattr(direct_file, "is_backup_dir", fake_is_backup_dir)
    monkeypatch.setattr(direct_file, "find_backups", fake_find_backups)

    resolved, reason = direct_file.resolve_backup_for_direct_file(source_file, DirectFileKind.APP_DATA)
    assert not reason
    assert resolved == backup_a


def test_resolve_reports_ambiguity_when_scores_tie(monkeypatch, tmp_path: Path) -> None:
    backup_a = tmp_path / "A" / "backup_a"
    backup_b = tmp_path / "B" / "backup_b"
    (backup_a / "APKFILE").mkdir(parents=True)
    (backup_b / "APKFILE").mkdir(parents=True)
    source_file = tmp_path / "outside" / "sample.data"
    source_file.parent.mkdir(parents=True)
    source_file.write_bytes(b"x")

    def fake_is_backup_dir(_path: Path) -> bool:
        return False

    def fake_find_backups(_root: Path) -> list[SimpleNamespace]:
        return [SimpleNamespace(path=backup_a), SimpleNamespace(path=backup_b)]

    monkeypatch.setattr(direct_file, "is_backup_dir", fake_is_backup_dir)
    monkeypatch.setattr(direct_file, "find_backups", fake_find_backups)

    resolved, reason = direct_file.resolve_backup_for_direct_file(source_file, DirectFileKind.APP_DATA)
    assert resolved is None
    assert "multiple nearby backups matched" in reason


def test_plan_prefers_single_resolved_backup_and_skips_unresolved(monkeypatch, tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    primary = tmp_path / "com.example.good.data"
    secondary = tmp_path / "com.example.missing.data"
    primary.write_bytes(b"x")
    secondary.write_bytes(b"x")

    def fake_resolve(file_path: Path, _kind: DirectFileKind) -> tuple[Path | None, str]:
        if file_path == primary:
            return backup, ""
        return None, "could not locate a Smart Switch backup nearby"

    monkeypatch.setattr(direct_file, "resolve_backup_for_direct_file", fake_resolve)

    result = direct_file.plan_direct_import([primary, secondary])
    assert result.plan is not None
    assert result.plan.staged_backup_dir is None
    assert result.plan.backup_dir == backup
    assert result.plan.backup_files == [primary]
    assert any("missing.data" in line for line in result.notices)


def test_plan_stages_when_files_resolve_to_multiple_backups(monkeypatch, tmp_path: Path) -> None:
    backup_a = tmp_path / "backup_a"
    backup_b = tmp_path / "backup_b"
    staged = tmp_path / "smartswitch-explorer-direct-staged"
    file_a = tmp_path / "a.data"
    file_b = tmp_path / "b.data"
    file_a.write_bytes(b"a")
    file_b.write_bytes(b"b")

    def fake_resolve(file_path: Path, _kind: DirectFileKind) -> tuple[Path | None, str]:
        if file_path == file_a:
            return backup_a, ""
        return backup_b, ""

    def fake_stage(files: list[Path]) -> tuple[Path, list[str]]:
        assert files == [file_a, file_b]
        return staged, ["staged warning"]

    monkeypatch.setattr(direct_file, "resolve_backup_for_direct_file", fake_resolve)
    monkeypatch.setattr(direct_file, "stage_direct_files_as_backup", fake_stage)

    result = direct_file.plan_direct_import([file_a, file_b])
    assert result.plan is not None
    assert result.plan.backup_dir == staged
    assert result.plan.staged_backup_dir == staged
    assert result.plan.backup_files == [file_a, file_b]
    assert any("multiple backups" in line for line in result.plan.notices)


def test_plan_stages_when_no_backup_is_found(monkeypatch, tmp_path: Path) -> None:
    staged = tmp_path / "smartswitch-explorer-direct-staged"
    standalone = tmp_path / "Message.smem"
    standalone.write_bytes(b"x")

    def fake_resolve(_file_path: Path, _kind: DirectFileKind) -> tuple[Path | None, str]:
        return None, "could not locate a Smart Switch backup nearby"

    def fake_stage(files: list[Path]) -> tuple[Path, list[str]]:
        assert files == [standalone]
        return staged, ["staged warning"]

    monkeypatch.setattr(direct_file, "resolve_backup_for_direct_file", fake_resolve)
    monkeypatch.setattr(direct_file, "stage_direct_files_as_backup", fake_stage)

    result = direct_file.plan_direct_import([standalone])
    assert result.plan is not None
    assert result.plan.backup_dir == staged
    assert result.plan.staged_backup_dir == staged
    assert result.plan.backup_files == [standalone]
    assert result.plan.notices == ["staged warning"]


def test_cleanup_staged_backup_dirs_only_removes_staged_prefix(tmp_path: Path) -> None:
    staged = tmp_path / "smartswitch-explorer-direct-example"
    regular = tmp_path / "keep-this-dir"
    kept_staged = tmp_path / "smartswitch-explorer-direct-keep"
    staged.mkdir(parents=True)
    regular.mkdir(parents=True)
    kept_staged.mkdir(parents=True)

    warnings = direct_file.cleanup_staged_backup_dirs(
        [staged, regular, kept_staged],
        keep={direct_file.path_key(kept_staged)},
    )
    assert warnings == []
    assert not staged.exists()
    assert regular.exists()
    assert kept_staged.exists()

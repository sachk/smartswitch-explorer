from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from smartswitch_core.export import write_manifest
from smartswitch_core.models import ExportResult


def _safe_extract_zip(zip_path: Path, destination: Path) -> tuple[int, list[str]]:
    warnings: list[str] = []
    extracted = 0
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()

    try:
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                rel = info.filename.replace("\\", "/").lstrip("/")
                target = (destination / rel).resolve()
                if not str(target).startswith(str(destination_root)):
                    warnings.append(f"Skipped unsafe zip entry in {zip_path.name}: {info.filename}")
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    target.write_bytes(zf.read(info))
                    extracted += 1
                except (OSError, KeyError) as exc:
                    warnings.append(f"Failed to extract {info.filename}: {exc}")
    except (OSError, zipfile.BadZipFile) as exc:
        warnings.append(f"Failed to open zip {zip_path.name}: {exc}")

    return extracted, warnings


def _copy_tree(source: Path, destination: Path) -> tuple[int, list[str]]:
    warnings: list[str] = []
    copied = 0
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(source)
        target = destination / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied += 1
        except OSError as exc:
            warnings.append(f"Failed to copy {path.name}: {exc}")
    return copied, warnings


def export_other_entry(backup_dir: Path, entry_name: str, out_dir: Path) -> ExportResult:
    outputs: list[Path] = []
    warnings: list[str] = []
    errors: list[str] = []

    source = backup_dir / entry_name
    if not source.exists():
        return ExportResult(ok=False, outputs=outputs, warnings=warnings, errors=[f"Missing entry: {entry_name}"])

    entry_out = out_dir / "other_data" / entry_name
    raw_out = entry_out / "raw"
    copied_files = 0
    extracted_archives = 0

    if source.is_dir():
        copied_files, local_warnings = _copy_tree(source, raw_out)
        warnings.extend(local_warnings)
        outputs.append(raw_out)

        for archive in source.rglob("*"):
            if not archive.is_file():
                continue
            if not zipfile.is_zipfile(archive):
                continue
            archive_rel = archive.relative_to(source)
            extract_dest = entry_out / "extracted" / archive_rel.with_suffix("")
            extracted, local_warnings = _safe_extract_zip(archive, extract_dest)
            warnings.extend(local_warnings)
            if extracted:
                extracted_archives += 1
                outputs.append(extract_dest)
    elif source.is_file():
        raw_out.mkdir(parents=True, exist_ok=True)
        try:
            target = raw_out / source.name
            shutil.copy2(source, target)
            outputs.append(target)
            copied_files = 1
        except OSError as exc:
            errors.append(f"Failed to copy {entry_name}: {exc}")

        if zipfile.is_zipfile(source):
            extract_dest = entry_out / "extracted" / source.stem
            extracted, local_warnings = _safe_extract_zip(source, extract_dest)
            warnings.extend(local_warnings)
            if extracted:
                extracted_archives = 1
                outputs.append(extract_dest)
    else:
        errors.append(f"Unsupported entry type: {entry_name}")

    manifest = {
        "entry": entry_name,
        "source": str(source),
        "copied_files": copied_files,
        "extracted_archives": extracted_archives,
        "warnings": warnings,
        "errors": errors,
    }
    manifest_path = entry_out / "manifest.json"
    write_manifest(manifest_path, manifest)
    outputs.append(manifest_path)

    return ExportResult(ok=not errors, outputs=outputs, warnings=warnings, errors=errors)

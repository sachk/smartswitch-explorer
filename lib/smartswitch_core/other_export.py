from __future__ import annotations

import io
import shutil
import zipfile
from pathlib import Path

from smartswitch_core.category_grouping import is_private_root_metadata_name
from smartswitch_core.crypto.common import DEFAULT_DUMMY_HEX
from smartswitch_core.crypto.smartdecrypt import decode_iv_prefix_payload, is_probably_encrypted_name
from smartswitch_core.export import write_manifest
from smartswitch_core.models import ExportResult
from smartswitch_core.path_safety import safe_output_path


def _safe_extract_zip(zip_path: Path, destination: Path) -> tuple[int, list[str]]:
    warnings: list[str] = []
    extracted = 0
    destination.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                try:
                    target = safe_output_path(destination, info.filename)
                except ValueError:
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


def _safe_extract_zip_bytes(raw_zip: bytes, destination: Path, source_name: str) -> tuple[int, list[str]]:
    warnings: list[str] = []
    extracted = 0
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                try:
                    target = safe_output_path(destination, info.filename)
                except ValueError as exc:
                    warnings.append(f"Skipped unsafe zip entry in {source_name}: {info.filename} ({exc})")
                    continue
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zf.read(info))
                    extracted += 1
                except (OSError, KeyError) as exc:
                    warnings.append(f"Failed to extract decoded zip entry {info.filename}: {exc}")
    except (OSError, zipfile.BadZipFile) as exc:
        warnings.append(f"Failed to parse decoded zip payload from {source_name}: {exc}")
    return extracted, warnings


def _copy_tree(source: Path, destination: Path) -> tuple[int, list[str]]:
    warnings: list[str] = []
    copied = 0
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.rglob("*"):
        if path.is_symlink() or not path.is_file():
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


def _decode_and_write_if_encrypted(
    raw: bytes,
    *,
    name_hint: str,
    destination: Path,
    dummy_hex: str,
    backup_password: str | None,
) -> tuple[Path | None, int, list[str]]:
    warnings: list[str] = []
    if not is_probably_encrypted_name(name_hint):
        return None, 0, warnings

    try:
        decoded = decode_iv_prefix_payload(
            raw,
            dummy_hex=dummy_hex,
            password=backup_password,
            name_hint=name_hint,
        )
    except ValueError:
        return None, 0, warnings

    target = destination
    if not target.suffix and decoded.extension:
        target = target.with_suffix(decoded.extension)
    elif target.suffix and target.suffix.lower() in {".enc", ".exml", ".encp", ".bk"}:
        target = target.with_suffix(decoded.extension)

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(decoded.payload)
    except OSError as exc:
        warnings.append(f"Failed to write decoded payload for {name_hint}: {exc}")
        return None, 0, warnings

    nested_count = 0
    if decoded.kind == "zip":
        nested_dir = target.with_suffix("")
        nested_count, nested_warnings = _safe_extract_zip_bytes(decoded.payload, nested_dir, name_hint)
        warnings.extend(nested_warnings)

    return target, nested_count, warnings


def export_other_entry(
    backup_dir: Path,
    entry_name: str,
    out_dir: Path,
    *,
    category: str = "other_data",
    dummy_hex: str = DEFAULT_DUMMY_HEX,
    backup_password: str | None = None,
) -> ExportResult:
    outputs: list[Path] = []
    warnings: list[str] = []
    errors: list[str] = []

    unresolved_source = backup_dir / entry_name
    if unresolved_source.is_symlink():
        return ExportResult(ok=False, outputs=outputs, warnings=warnings, errors=["Symbolic links are not exportable"])
    try:
        source = safe_output_path(backup_dir, entry_name)
    except ValueError:
        return ExportResult(ok=False, outputs=outputs, warnings=warnings, errors=["Invalid top-level backup entry"])
    if source.parent != backup_dir.resolve():
        return ExportResult(ok=False, outputs=outputs, warnings=warnings, errors=["Invalid top-level backup entry"])
    if is_private_root_metadata_name(entry_name):
        return ExportResult(
            ok=False,
            outputs=outputs,
            warnings=warnings,
            errors=["Root backup metadata is intentionally excluded from export"],
        )
    if not source.exists():
        return ExportResult(ok=False, outputs=outputs, warnings=warnings, errors=[f"Missing entry: {entry_name}"])

    try:
        category_out = safe_output_path(out_dir, category)
        entry_out = safe_output_path(category_out, entry_name)
    except ValueError:
        return ExportResult(ok=False, outputs=outputs, warnings=warnings, errors=["Invalid export category"])
    raw_out = entry_out / "raw"
    decoded_out = entry_out / "decoded"
    copied_files = 0
    extracted_archives = 0
    decoded_files = 0
    decoded_nested_zip_entries = 0

    if source.is_dir():
        copied_files, local_warnings = _copy_tree(source, raw_out)
        warnings.extend(local_warnings)
        outputs.append(raw_out)

        for path in source.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(source)
            try:
                raw = path.read_bytes()
            except OSError as exc:
                warnings.append(f"Failed to read {path.name}: {exc}")
                continue
            decoded_path, nested_count, local_warnings = _decode_and_write_if_encrypted(
                raw,
                name_hint=path.name,
                destination=decoded_out / rel,
                dummy_hex=dummy_hex,
                backup_password=backup_password,
            )
            warnings.extend(local_warnings)
            if decoded_path is not None:
                decoded_files += 1
                decoded_nested_zip_entries += nested_count
                outputs.append(decoded_path)

        for archive in source.rglob("*"):
            if archive.is_symlink() or not archive.is_file():
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
                # Try decoding encrypted members of this archive.
                try:
                    with zipfile.ZipFile(archive) as zf:
                        for info in zf.infolist():
                            if info.is_dir():
                                continue
                            try:
                                raw = zf.read(info)
                            except KeyError:
                                continue
                            decoded_root = decoded_out / archive_rel.with_suffix("")
                            try:
                                decoded_destination = safe_output_path(decoded_root, info.filename)
                            except ValueError:
                                warnings.append(f"Skipped unsafe encrypted zip entry in {archive.name}: {info.filename}")
                                continue
                            decoded_path, nested_count, local_warnings = _decode_and_write_if_encrypted(
                                raw,
                                name_hint=Path(info.filename).name,
                                destination=decoded_destination,
                                dummy_hex=dummy_hex,
                                backup_password=backup_password,
                            )
                            warnings.extend(local_warnings)
                            if decoded_path is not None:
                                decoded_files += 1
                                decoded_nested_zip_entries += nested_count
                                outputs.append(decoded_path)
                except (OSError, zipfile.BadZipFile) as exc:
                    warnings.append(f"Failed to inspect archive for encrypted members {archive.name}: {exc}")
    elif source.is_file():
        raw_out.mkdir(parents=True, exist_ok=True)
        try:
            target = raw_out / source.name
            shutil.copy2(source, target)
            outputs.append(target)
            copied_files = 1
        except OSError as exc:
            errors.append(f"Failed to copy {entry_name}: {exc}")

        if source.exists():
            try:
                raw = source.read_bytes()
            except OSError as exc:
                warnings.append(f"Failed to read {entry_name}: {exc}")
            else:
                decoded_path, nested_count, local_warnings = _decode_and_write_if_encrypted(
                    raw,
                    name_hint=source.name,
                    destination=decoded_out / source.name,
                    dummy_hex=dummy_hex,
                    backup_password=backup_password,
                )
                warnings.extend(local_warnings)
                if decoded_path is not None:
                    decoded_files += 1
                    decoded_nested_zip_entries += nested_count
                    outputs.append(decoded_path)

        if zipfile.is_zipfile(source):
            extract_dest = entry_out / "extracted" / source.stem
            extracted, local_warnings = _safe_extract_zip(source, extract_dest)
            warnings.extend(local_warnings)
            if extracted:
                extracted_archives = 1
                outputs.append(extract_dest)
                try:
                    with zipfile.ZipFile(source) as zf:
                        for info in zf.infolist():
                            if info.is_dir():
                                continue
                            try:
                                raw = zf.read(info)
                            except KeyError:
                                continue
                            try:
                                decoded_destination = safe_output_path(decoded_out / source.stem, info.filename)
                            except ValueError:
                                warnings.append(f"Skipped unsafe encrypted zip entry in {source.name}: {info.filename}")
                                continue
                            decoded_path, nested_count, local_warnings = _decode_and_write_if_encrypted(
                                raw,
                                name_hint=Path(info.filename).name,
                                destination=decoded_destination,
                                dummy_hex=dummy_hex,
                                backup_password=backup_password,
                            )
                            warnings.extend(local_warnings)
                            if decoded_path is not None:
                                decoded_files += 1
                                decoded_nested_zip_entries += nested_count
                                outputs.append(decoded_path)
                except (OSError, zipfile.BadZipFile) as exc:
                    warnings.append(f"Failed to inspect archive for encrypted members {source.name}: {exc}")
    else:
        errors.append(f"Unsupported entry type: {entry_name}")

    manifest = {
        "entry": entry_name,
        "source_entry": source.name,
        "copied_files": copied_files,
        "extracted_archives": extracted_archives,
        "decoded_files": decoded_files,
        "decoded_nested_zip_entries": decoded_nested_zip_entries,
        "warnings": warnings,
        "errors": errors,
    }
    manifest_path = entry_out / "manifest.json"
    write_manifest(manifest_path, manifest)
    outputs.append(manifest_path)

    return ExportResult(ok=not errors, outputs=outputs, warnings=warnings, errors=errors)


def export_storage_entry(
    backup_dir: Path,
    entry_name: str,
    out_dir: Path,
    *,
    dummy_hex: str = DEFAULT_DUMMY_HEX,
    backup_password: str | None = None,
) -> ExportResult:
    return export_other_entry(
        backup_dir,
        entry_name,
        out_dir,
        category="storage",
        dummy_hex=dummy_hex,
        backup_password=backup_password,
    )


def export_settings_entry(
    backup_dir: Path,
    entry_name: str,
    out_dir: Path,
    *,
    dummy_hex: str = DEFAULT_DUMMY_HEX,
    backup_password: str | None = None,
) -> ExportResult:
    return export_other_entry(
        backup_dir,
        entry_name,
        out_dir,
        category="settings",
        dummy_hex=dummy_hex,
        backup_password=backup_password,
    )

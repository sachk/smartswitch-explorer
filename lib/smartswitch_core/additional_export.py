from __future__ import annotations

import csv
import io
import json
import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath

from smartswitch_core.crypto.common import DEFAULT_DUMMY_HEX
from smartswitch_core.crypto.smartdecrypt import (
    decode_iv_prefix_payload,
    extract_xml_region,
)
from smartswitch_core.export import write_manifest
from smartswitch_core.models import ExportResult


def _copy_tree(source_dir: Path, destination_dir: Path) -> tuple[int, list[Path], list[str]]:
    outputs: list[Path] = []
    warnings: list[str] = []
    copied = 0

    if not source_dir.is_dir():
        return copied, outputs, [f"Missing directory: {source_dir}"]

    destination_dir.mkdir(parents=True, exist_ok=True)
    for source in source_dir.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(source_dir)
        target = destination_dir / relative
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied += 1
        except OSError as exc:
            warnings.append(f"Failed to copy {source.name}: {exc}")
    outputs.append(destination_dir)
    return copied, outputs, warnings


def _safe_target(root: Path, relative: str) -> Path:
    cleaned = relative.replace("\\", "/").lstrip("/")
    candidate = (root / cleaned).resolve()
    root_resolved = root.resolve()
    if not str(candidate).startswith(str(root_resolved)):
        raise ValueError("Unsafe output path")
    return candidate


def _extract_zip_bytes(raw_zip: bytes, destination: Path) -> tuple[int, list[str]]:
    warnings: list[str] = []
    extracted = 0
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                try:
                    target = _safe_target(destination, info.filename)
                except ValueError as exc:
                    warnings.append(f"Skipped unsafe nested zip path {info.filename}: {exc}")
                    continue
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zf.read(info))
                    extracted += 1
                except (OSError, KeyError) as exc:
                    warnings.append(f"Failed to extract nested zip entry {info.filename}: {exc}")
    except (OSError, zipfile.BadZipFile) as exc:
        warnings.append(f"Failed to read nested zip payload: {exc}")
    return extracted, warnings


def _load_watch_name_map(source_dir: Path) -> dict[str, str]:
    mapping_path = source_dir / f"{source_dir.name}_FileEncryptionInfo.json"
    if not mapping_path.exists():
        return {}
    try:
        payload = json.loads(mapping_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

    out: dict[str, str] = {}
    if not isinstance(payload, dict):
        return out
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        out[PurePosixPath(key).name] = value
    return out


def _decoded_watch_target_path(decoded_root: Path, source_name: str, mapped_path: str | None, extension: str) -> Path:
    if mapped_path:
        candidate = mapped_path.lstrip("/")
        relative = Path(candidate)
        if not relative.suffix and extension:
            relative = relative.with_suffix(extension)
        return _safe_target(decoded_root, relative.as_posix())

    base_name = source_name[:-4] if source_name.endswith("encp") else source_name
    relative = Path(base_name)
    if not relative.suffix and extension:
        relative = relative.with_suffix(extension)
    return _safe_target(decoded_root, relative.as_posix())


def export_media_directory(kind: str, backup_dir: Path, out_dir: Path) -> ExportResult:
    outputs: list[Path] = []
    warnings: list[str] = []
    errors: list[str] = []

    if kind not in {"photos", "videos"}:
        errors.append(f"Unsupported media kind: {kind}")
        return ExportResult(ok=False, outputs=outputs, warnings=warnings, errors=errors)

    source_names = ["Photo", "PHOTO_ORIGIN"] if kind == "photos" else ["Video", "VIDEO_ORIGIN"]
    target_dir = out_dir / "media" / kind
    per_source: dict[str, int] = {}
    copied = 0

    for source_name in source_names:
        source_dir = backup_dir / source_name
        source_target = target_dir / source_name
        local_copied, local_outputs, local_warnings = _copy_tree(source_dir, source_target)
        per_source[source_name] = local_copied
        copied += local_copied
        outputs.extend(local_outputs)
        warnings.extend(local_warnings)

    manifest = {
        "kind": kind,
        "sources": source_names,
        "copied_per_source": per_source,
        "copied_files": copied,
        "warnings": warnings,
        "errors": errors,
    }
    manifest_path = out_dir / "media" / f"manifest_{kind}.json"
    write_manifest(manifest_path, manifest)
    outputs.append(manifest_path)

    return ExportResult(ok=not errors, outputs=outputs, warnings=warnings, errors=errors)


def export_watch_backup(
    kind: str,
    backup_dir: Path,
    out_dir: Path,
    *,
    dummy_hex: str = DEFAULT_DUMMY_HEX,
) -> ExportResult:
    outputs: list[Path] = []
    warnings: list[str] = []
    errors: list[str] = []

    if kind not in {"current", "backup"}:
        errors.append(f"Unsupported watch backup kind: {kind}")
        return ExportResult(ok=False, outputs=outputs, warnings=warnings, errors=errors)

    source_name = "GALAXYWATCH_CURRENT" if kind == "current" else "GALAXYWATCH_BACKUP"
    source_dir = backup_dir / source_name
    target_dir = out_dir / "galaxy_watch" / kind
    copied, local_outputs, local_warnings = _copy_tree(source_dir, target_dir)
    outputs.extend(local_outputs)
    warnings.extend(local_warnings)

    name_map = _load_watch_name_map(source_dir)
    decoded_root = target_dir / "decoded"
    decoded_count = 0
    extracted_nested = 0
    unresolved: list[str] = []

    for source in sorted(source_dir.glob("*encp")):
        if not source.is_file():
            continue
        try:
            decoded = decode_iv_prefix_payload(
                source.read_bytes(),
                dummy_hex=dummy_hex,
                name_hint=source.name,
            )
        except ValueError as exc:
            warnings.append(f"Failed to decrypt {source.name}: {exc}")
            unresolved.append(source.name)
            continue

        mapped = name_map.get(source.name)
        try:
            target = _decoded_watch_target_path(decoded_root, source.name, mapped, decoded.extension)
        except ValueError as exc:
            warnings.append(f"Skipping unsafe mapped path for {source.name}: {exc}")
            unresolved.append(source.name)
            continue

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(decoded.payload)
            decoded_count += 1
            outputs.append(target)
        except OSError as exc:
            warnings.append(f"Failed to write decoded watch file {source.name}: {exc}")
            unresolved.append(source.name)
            continue

        if decoded.kind == "zip":
            nested_dir = target.with_suffix("")
            nested_count, nested_warnings = _extract_zip_bytes(decoded.payload, nested_dir)
            warnings.extend(nested_warnings)
            if nested_count:
                extracted_nested += nested_count
                outputs.append(nested_dir)

    manifest = {
        "kind": kind,
        "source": str(source_dir),
        "copied_files": copied,
        "decoded_files": decoded_count,
        "decoded_nested_zip_entries": extracted_nested,
        "unresolved_encrypted_files": unresolved,
        "warnings": warnings,
        "errors": errors,
    }
    manifest_path = out_dir / "galaxy_watch" / f"manifest_{kind}.json"
    write_manifest(manifest_path, manifest)
    outputs.append(manifest_path)

    return ExportResult(ok=not errors, outputs=outputs, warnings=warnings, errors=errors)


def export_contacts(
    backup_dir: Path,
    out_dir: Path,
    *,
    output_format: str = "csv",
) -> ExportResult:
    outputs: list[Path] = []
    warnings: list[str] = []
    errors: list[str] = []

    contact_dir = backup_dir / "CONTACT"
    contacts_out = out_dir / "contacts"
    contacts_out.mkdir(parents=True, exist_ok=True)
    fmt = output_format.lower().strip()
    if fmt not in {"csv", "native"}:
        warnings.append(f"Unknown contacts format '{output_format}', defaulting to csv")
        fmt = "csv"

    copied = 0
    if fmt == "native":
        copied, local_outputs, local_warnings = _copy_tree(contact_dir, contacts_out / "native")
        outputs.extend(local_outputs)
        warnings.extend(local_warnings)
    else:
        csv_out = contacts_out / "csv"
        csv_out.mkdir(parents=True, exist_ok=True)
        for source in sorted(contact_dir.glob("*.csv")):
            try:
                shutil.copy2(source, csv_out / source.name)
                copied += 1
            except OSError as exc:
                warnings.append(f"Failed to copy {source.name}: {exc}")
        if copied == 0:
            spbm = contact_dir / "Contact.spbm"
            if spbm.exists() and zipfile.is_zipfile(spbm):
                try:
                    with zipfile.ZipFile(spbm) as zf:
                        for info in zf.infolist():
                            name = PurePosixPath(info.filename).name
                            if not name.lower().endswith(".csv"):
                                continue
                            (csv_out / name).write_bytes(zf.read(info))
                            copied += 1
                except (OSError, zipfile.BadZipFile, KeyError) as exc:
                    warnings.append(f"Failed to read Contact.spbm: {exc}")
        if copied == 0:
            warnings.append("No contact CSV files found")
        outputs.append(csv_out)

    manifest = {
        "format": fmt,
        "copied_files": copied,
        "warnings": warnings,
        "errors": errors,
    }
    manifest_path = contacts_out / "manifest.json"
    write_manifest(manifest_path, manifest)
    outputs.append(manifest_path)
    return ExportResult(ok=not errors, outputs=outputs, warnings=warnings, errors=errors)


def _decrypt_call_log_exml(raw: bytes, dummy_hex: str) -> bytes:
    decoded = decode_iv_prefix_payload(
        raw,
        dummy_hex=dummy_hex,
        name_hint="call_log.exml",
        xml_root_tag="CallLogs",
    )
    return extract_xml_region(decoded.payload, root_tag="CallLogs")


def _call_log_rows(xml_payload: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(xml_payload.decode("utf-8", "replace"))
    rows: list[dict[str, str]] = []
    for entry in root.findall(".//CallLog"):
        row: dict[str, str] = {str(k): str(v) for k, v in entry.attrib.items()}
        for child in list(entry):
            tag = str(child.tag)
            if tag not in row:
                row[tag] = (child.text or "").strip()
        rows.append(row)
    return rows


def _write_rows_csv(rows: list[dict[str, str]], target: Path) -> None:
    if not rows:
        target.write_text("call_log\n", encoding="utf-8")
        return

    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)

    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in columns})


def export_call_log(
    backup_dir: Path,
    out_dir: Path,
    *,
    output_format: str = "csv",
    dummy_hex: str = DEFAULT_DUMMY_HEX,
) -> ExportResult:
    outputs: list[Path] = []
    warnings: list[str] = []
    errors: list[str] = []

    calllog_dir = backup_dir / "CALLLOG"
    zip_path = calllog_dir / "CALLLOG.zip"
    out_root = out_dir / "call_log"
    out_root.mkdir(parents=True, exist_ok=True)

    fmt = output_format.lower().strip()
    if fmt not in {"csv", "native"}:
        warnings.append(f"Unknown call log format '{output_format}', defaulting to csv")
        fmt = "csv"

    if not zip_path.exists():
        errors.append("Missing CALLLOG/CALLLOG.zip")
    elif fmt == "native":
        target = out_root / zip_path.name
        try:
            shutil.copy2(zip_path, target)
            outputs.append(target)
        except OSError as exc:
            errors.append(f"Failed to copy {zip_path.name}: {exc}")
    else:
        try:
            with zipfile.ZipFile(zip_path) as zf:
                exml_name = ""
                for info in zf.infolist():
                    if PurePosixPath(info.filename).name.lower().endswith(".exml"):
                        exml_name = info.filename
                        break
                if not exml_name:
                    raise ValueError("Encrypted call log .exml was not found")
                encrypted = zf.read(exml_name)
        except (OSError, zipfile.BadZipFile, KeyError, ValueError) as exc:
            errors.append(f"Failed to read call log archive: {exc}")
        else:
            try:
                decrypted_xml = _decrypt_call_log_exml(encrypted, dummy_hex)
                xml_path = out_root / "call_log.xml"
                xml_path.write_bytes(decrypted_xml)
                outputs.append(xml_path)

                rows = _call_log_rows(decrypted_xml)
                csv_path = out_root / "call_log.csv"
                _write_rows_csv(rows, csv_path)
                outputs.append(csv_path)
            except Exception as exc:  # pragma: no cover - defensive boundary
                errors.append(f"Failed to decrypt/convert call log: {exc}")

    manifest = {
        "format": fmt,
        "warnings": warnings,
        "errors": errors,
    }
    manifest_path = out_root / "manifest.json"
    write_manifest(manifest_path, manifest)
    outputs.append(manifest_path)

    return ExportResult(ok=not errors, outputs=outputs, warnings=warnings, errors=errors)

from __future__ import annotations

import csv
import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath

from Crypto.Cipher import AES

from smartswitch_core.crypto.common import DEFAULT_DUMMY_HEX, derive_dummy_key
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


def export_media_directory(kind: str, backup_dir: Path, out_dir: Path) -> ExportResult:
    outputs: list[Path] = []
    warnings: list[str] = []
    errors: list[str] = []

    if kind not in {"photos", "videos"}:
        errors.append(f"Unsupported media kind: {kind}")
        return ExportResult(ok=False, outputs=outputs, warnings=warnings, errors=errors)

    source_name = "PHOTO_ORIGIN" if kind == "photos" else "VIDEO_ORIGIN"
    source_dir = backup_dir / source_name
    target_dir = out_dir / "media" / kind
    copied, local_outputs, local_warnings = _copy_tree(source_dir, target_dir)
    outputs.extend(local_outputs)
    warnings.extend(local_warnings)

    manifest = {
        "kind": kind,
        "source": str(source_dir),
        "copied_files": copied,
        "warnings": warnings,
        "errors": errors,
    }
    manifest_path = out_dir / "media" / f"manifest_{kind}.json"
    write_manifest(manifest_path, manifest)
    outputs.append(manifest_path)

    return ExportResult(ok=not errors, outputs=outputs, warnings=warnings, errors=errors)


def export_watch_backup(kind: str, backup_dir: Path, out_dir: Path) -> ExportResult:
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

    manifest = {
        "kind": kind,
        "source": str(source_dir),
        "copied_files": copied,
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
    if len(raw) < 32:
        raise ValueError("Encrypted call log payload too small")
    iv = raw[:16]
    ciphertext = raw[16:]
    ciphertext = ciphertext[: len(ciphertext) - (len(ciphertext) % 16)]
    if not ciphertext:
        raise ValueError("Missing aligned encrypted call log payload")

    decrypted = AES.new(derive_dummy_key(dummy_hex), AES.MODE_CBC, iv).decrypt(ciphertext)
    start = decrypted.find(b"<?xml")
    if start == -1:
        start = decrypted.find(b"<CallLogs")
    if start == -1:
        raise ValueError("Decrypted call log XML header not found")

    end_marker = b"</CallLogs>"
    end = decrypted.rfind(end_marker)
    if end != -1:
        return decrypted[start : end + len(end_marker)]
    return decrypted[start:].rstrip(b"\x00")


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

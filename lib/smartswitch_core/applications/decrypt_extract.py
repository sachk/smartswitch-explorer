from __future__ import annotations

import io
import json
import shutil
import string
import struct
import tarfile
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import Path

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from smartswitch_core.applications.android_backup import (
    AndroidBackupDecodeError,
    decode_android_backup_file,
)
from smartswitch_core.crypto.common import DEFAULT_DUMMY_HEX, DEFAULT_PENC_IV, derive_dummy_key
from smartswitch_core.export import write_manifest
from smartswitch_core.models import ExportResult
from smartswitch_core.path_safety import safe_output_path


class AppDataPasswordError(ValueError):
    """The Android backup master key could not be unlocked."""


class AppApkDecryptionError(ValueError):
    """The legacy Smart Switch APK key did not decrypt a PENC payload."""


_CREDENTIAL_FAILURE_PHASES = {
    "master-key padding failure",
    "malformed master-key structure",
    "master-key checksum mismatch",
}

_PASSWORD_FIELD_NAMES = {
    "backuppassword",
    "dummy",
    "encryptionkey",
    "encryptionpassword",
    "password",
    "securitykey",
}


def _metadata_password_candidates(backup_dir: Path) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    metadata_path = backup_dir / "SmartSwitchBackup.json"
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            metadata = None

        def visit(value: object) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    normalized = "".join(char for char in str(key).lower() if char.isalnum())
                    if normalized in _PASSWORD_FIELD_NAMES and isinstance(child, str) and child:
                        source = f"{metadata_path.name}:{key}"
                        if normalized == "dummy" and len(child) == 64:
                            try:
                                decoded = bytes.fromhex(child).decode("utf-8")
                            except (UnicodeDecodeError, ValueError):
                                pass
                            else:
                                if all(char in string.printable for char in decoded):
                                    candidates.append((f"{source} (hex decoded)", decoded))
                        candidates.append((source, child))
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(metadata)

    history_path = backup_dir / "backupHistoryInfo.xml"
    if history_path.exists():
        try:
            root = ET.fromstring(history_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ET.ParseError):
            root = None
        if root is not None:
            for element in root.iter():
                if element.tag.rsplit("}", 1)[-1].lower() == "dummy" and element.text:
                    candidates.append((f"{history_path.name}:Dummy", element.text.strip()))
                    break
    return candidates


def _safe_join(root: Path, relative_name: str) -> Path:
    return safe_output_path(root, relative_name)


def _decrypt_penc(path: Path, dummy: str) -> bytes:
    raw = path.read_bytes()
    if len(raw) < 20:
        raise ValueError(".penc file too small")

    encrypted_size = int.from_bytes(raw[:4], "big")
    if encrypted_size <= 0 or encrypted_size > 0x100010:
        raise ValueError(f"Invalid .penc encrypted segment size: {encrypted_size}")
    encrypted_end = 4 + encrypted_size
    if encrypted_end > len(raw) or encrypted_size % 16:
        raise ValueError("Truncated or unaligned .penc encrypted segment")

    encrypted = raw[4:encrypted_end]
    decrypted = AES.new(derive_dummy_key(dummy), AES.MODE_CBC, DEFAULT_PENC_IV).decrypt(encrypted)
    try:
        decrypted = unpad(decrypted, 16)
    except ValueError as exc:
        raise AppApkDecryptionError("Smart Switch backup dummy key was rejected") from exc

    apk = decrypted + raw[encrypted_end:]
    if not apk.startswith(b"PK\x03\x04"):
        raise AppApkDecryptionError("Smart Switch backup dummy key was rejected")
    return apk


def _decode_penc_with_candidates(
    path: Path,
    backup_dir: Path,
    *,
    supplied_password: str | None,
    fallback_password: str,
) -> tuple[bytes, str]:
    candidates = _metadata_password_candidates(backup_dir)
    if supplied_password is not None:
        candidates.insert(0, ("Export Options", supplied_password))
    candidates.append(("legacy Smart Switch key", fallback_password))

    seen: set[str] = set()
    for source, password in candidates:
        if password in seen:
            continue
        seen.add(password)
        try:
            return _decrypt_penc(path, password), source
        except AppApkDecryptionError:
            continue

    missing_metadata = not (backup_dir / "SmartSwitchBackup.json").exists()
    reason = (
        "SmartSwitchBackup.json is missing from this backup copy. "
        if missing_metadata
        else ""
    )
    raise AppApkDecryptionError(
        f"{reason}None of the available Smart Switch backup dummy keys could decrypt "
        "the PENC header. Export Application APKs to preserve the raw PENC file."
    )

def _extract_recoverable_penc_entries(
    path: Path,
    out_dir: Path,
) -> tuple[int, int, list[str]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    recovered = 0
    failed = 0
    warnings: list[str] = []

    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        return 0, 0, [f"PENC recovery could not read the APK directory: {exc}"]

    with archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            target: Path | None = None
            try:
                target = _safe_join(out_dir, member.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
            except (OSError, RuntimeError, ValueError, zipfile.BadZipFile):
                failed += 1
                if target is not None:
                    try:
                        target.unlink(missing_ok=True)
                    except OSError:
                        pass
                continue
            recovered += 1

    if failed:
        warnings.append(
            f"Recovered {recovered} unencrypted APK entries; {failed} entries overlap "
            "the encrypted PENC segment or failed integrity checks."
        )
    return recovered, failed, warnings



def _extract_local_entries(data: bytes, out_dir: Path) -> tuple[int, int, list[str]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    extracted = 0
    skipped = 0
    warnings: list[str] = []

    offset = 0
    while offset + 30 <= len(data) and data[offset : offset + 4] == b"PK\x03\x04":
        (
            _sig,
            _ver,
            _flag,
            method,
            _mtime,
            _mdate,
            _crc,
            compressed_size,
            _uncompressed_size,
            file_name_len,
            extra_len,
        ) = struct.unpack("<IHHHHHIIIHH", data[offset : offset + 30])

        name_start = offset + 30
        name_end = name_start + file_name_len
        data_start = name_end + extra_len
        data_end = data_start + compressed_size

        if data_end > len(data) or data_end <= offset:
            warnings.append("Truncated local entry encountered")
            break

        name = data[name_start:name_end].decode("utf-8", "replace")
        blob = data[data_start:data_end]

        try:
            target = _safe_join(out_dir, name)
            target.parent.mkdir(parents=True, exist_ok=True)

            if method == 0:
                target.write_bytes(blob)
                extracted += 1
            elif method == 8:
                try:
                    target.write_bytes(zlib.decompress(blob, -15))
                    extracted += 1
                except zlib.error:
                    skipped += 1
                    warnings.append(f"Failed to inflate: {name}")
            else:
                skipped += 1
                warnings.append(f"Unsupported compression method {method}: {name}")
        except (OSError, ValueError) as exc:
            skipped += 1
            warnings.append(f"Failed to write {name}: {exc}")

        offset = data_end

    return extracted, skipped, warnings


def _split_android_backup_header(raw: bytes, n_lines: int = 9) -> tuple[list[bytes], int]:
    lines: list[bytes] = []
    pos = 0
    for _ in range(n_lines):
        nl = raw.find(b"\n", pos)
        if nl == -1:
            raise ValueError("Truncated Android backup header")
        lines.append(raw[pos:nl].rstrip(b"\r"))
        pos = nl + 1
    return lines, pos


def _decode_data_payload(path: Path, password: str) -> tuple[bytes, dict]:
    return decode_android_backup_file(path, password)


def _decode_data_with_candidates(
    path: Path,
    backup_dir: Path,
    *,
    supplied_password: str | None,
    fallback_password: str,
) -> tuple[bytes, dict]:
    candidates: list[tuple[str, str]] = []
    if supplied_password is not None:
        candidates.append(("Export Options", supplied_password))
    candidates.extend(_metadata_password_candidates(backup_dir))
    candidates.extend(
        [
            ("Smart Switch legacy key", fallback_password),
            ("empty password", ""),
        ]
    )

    seen: set[str] = set()
    for source, password in candidates:
        if password in seen:
            continue
        seen.add(password)
        try:
            payload, meta = _decode_data_payload(path, password)
        except AndroidBackupDecodeError as exc:
            if exc.phase in _CREDENTIAL_FAILURE_PHASES:
                continue
            raise
        meta["password_source"] = source
        return payload, meta

    missing_metadata = not (backup_dir / "SmartSwitchBackup.json").exists()
    reason = (
        "SmartSwitchBackup.json is missing from this backup copy. "
        if missing_metadata
        else ""
    )
    if supplied_password is not None:
        reason += "The supplied app-data password was not accepted. "
    raise AppDataPasswordError(
        f"{reason}The Android app-data archive is encrypted, but none of the available "
        "Smart Switch keys could unlock it. Smart Switch may encrypt app data without "
        "showing a password prompt. Preserve all root JSON/XML metadata; if a backup "
        "password was configured, enter it under Export Options."
    )


def _safe_extract_tar(payload: bytes, out_dir: Path) -> tuple[int, list[str]]:
    warnings: list[str] = []
    if not payload:
        return 0, warnings

    out_dir.mkdir(parents=True, exist_ok=True)
    extracted = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as tf:
            for member in tf.getmembers():
                try:
                    target = _safe_join(out_dir, member.name)
                except ValueError:
                    warnings.append("Skipped unsafe tar member path")
                    continue
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    warnings.append("Skipped unsupported tar member type")
                    continue
                parent = target.parent
                parent.mkdir(parents=True, exist_ok=True)
                source = tf.extractfile(member)
                if source is None:
                    continue
                with source, target.open("wb") as handle:
                    handle.write(source.read())
                extracted += 1
    except tarfile.TarError as exc:
        warnings.append(f"Tar parse failed: {exc}")
    return extracted, warnings


def decrypt_extract_app(
    package_id: str,
    mode: str,
    backup_dir: Path,
    out_dir: Path,
    *,
    dummy_hex: str = DEFAULT_DUMMY_HEX,
    app_data_password: str | None = None,
    include_decrypt: bool = True,
    include_extract: bool = True,
    manifest_name: str = "manifest.json",
) -> ExportResult:
    outputs: list[Path] = []
    warnings: list[str] = []
    errors: list[str] = []

    apk_dir = backup_dir / "APKFILE"
    package_out = out_dir / package_id
    package_out.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, object] = {
        "package_id": package_id,
        "mode": mode,
        "include_decrypt": include_decrypt,
        "include_extract": include_extract,
        "penc": {},
        "data": {},
        "warnings": warnings,
        "errors": errors,
    }

    if mode in {"apk", "both"}:
        penc_path = apk_dir / f"{package_id}.penc"
        if penc_path.exists():
            try:
                dec, key_source = _decode_penc_with_candidates(
                    penc_path,
                    backup_dir,
                    supplied_password=app_data_password,
                    fallback_password=dummy_hex,
                )
                manifest["penc"] = {
                    "decrypted_size": len(dec),
                    "key_source": key_source,
                }
                if include_decrypt:
                    dec_path = package_out / f"{package_id}.decrypted.apk"
                    dec_path.write_bytes(dec)
                    outputs.append(dec_path)
                if include_extract:
                    files_dir = package_out / "apk_files"
                    extracted, skipped, local_warnings = _extract_local_entries(dec, files_dir)
                    warnings.extend(local_warnings)
                    outputs.append(files_dir)
                    manifest["penc"]["extracted_files"] = extracted
                    manifest["penc"]["skipped_files"] = skipped
            except AppApkDecryptionError as exc:
                errors.append(f"APK decrypt/extract failed for {package_id}: {exc}")
                if include_extract:
                    recovered_dir = package_out / "apk_recovered_files"
                    recovered, failed, recovery_warnings = _extract_recoverable_penc_entries(
                        penc_path,
                        recovered_dir,
                    )
                    warnings.extend(recovery_warnings)
                    manifest["penc"] = {
                        "recovered_unencrypted_files": recovered,
                        "unrecoverable_files": failed,
                    }
                    if recovered:
                        outputs.append(recovered_dir)
            except Exception as exc:  # pragma: no cover - defensive boundary
                errors.append(f"APK decrypt/extract failed for {package_id}: {exc}")
        else:
            warnings.append(f"Missing .penc file for {package_id}")

    if mode in {"data", "both"}:
        data_path = apk_dir / f"{package_id}.data"
        if data_path.exists():
            try:
                payload, meta = _decode_data_with_candidates(
                    data_path,
                    backup_dir,
                    supplied_password=app_data_password,
                    fallback_password=dummy_hex,
                )
                manifest["data"] = meta
                if include_decrypt:
                    tar_path = package_out / "data.decoded.tar"
                    tar_path.write_bytes(payload)
                    outputs.append(tar_path)
                if include_extract:
                    data_dir = package_out / "data_files"
                    extracted, local_warnings = _safe_extract_tar(payload, data_dir)
                    warnings.extend(local_warnings)
                    manifest["data"]["extracted_files"] = extracted
                    outputs.append(data_dir)
            except Exception as exc:  # pragma: no cover - defensive boundary
                errors.append(f"Data decode/extract failed for {package_id}: {exc}")
        else:
            warnings.append(f"Missing .data file for {package_id}")

    manifest_path = package_out / manifest_name
    write_manifest(manifest_path, manifest)
    outputs.append(manifest_path)

    return ExportResult(ok=not errors, outputs=outputs, warnings=warnings, errors=errors)


def copy_app_apk_payload(package_id: str, backup_dir: Path, out_dir: Path) -> ExportResult:
    outputs: list[Path] = []
    warnings: list[str] = []
    errors: list[str] = []

    apk_dir = backup_dir / "APKFILE"
    package_out = out_dir / package_id / "apk_payload"
    package_out.mkdir(parents=True, exist_ok=True)

    copied = 0
    candidates = [apk_dir / f"{package_id}.penc"]
    candidates.extend(sorted(apk_dir.glob(f"{package_id}*.apk")))

    for source in candidates:
        if not source.exists():
            continue
        try:
            target = package_out / source.name
            shutil.copy2(source, target)
            outputs.append(target)
            copied += 1
        except OSError as exc:
            warnings.append(f"Failed to copy {source.name}: {exc}")

    if copied == 0:
        warnings.append(f"No APK payload files found for {package_id}")

    manifest = {
        "package_id": package_id,
        "mode": "apk_payload_copy",
        "copied_files": copied,
        "warnings": warnings,
        "errors": errors,
    }
    manifest_path = package_out.parent / "manifest_apk.json"
    write_manifest(manifest_path, manifest)
    outputs.append(manifest_path)
    return ExportResult(ok=not errors, outputs=outputs, warnings=warnings, errors=errors)

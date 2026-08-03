from __future__ import annotations

import io
import json
import shutil
import stat
import string
import tarfile
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from smartswitch_core.applications.android_backup import (
    UNAVAILABLE_CREDENTIAL_MESSAGE,
    AndroidBackupDecodeError,
    AndroidBackupMetadata,
    decode_android_backup_to_tar,
)
from smartswitch_core.archive_safety import (
    MAX_APK_OUTPUT_BYTES,
    ArchiveBudget,
    ArchiveLimitError,
    DiskSpaceGuard,
)
from smartswitch_core.crypto.common import (
    DEFAULT_DUMMY_HEX,
    DEFAULT_PENC_IV,
    derive_dummy_key,
)
from smartswitch_core.crypto.session_credentials import (
    SessionCredential,
    SessionCredentialError,
    load_session_credential,
)
from smartswitch_core.export import write_manifest
from smartswitch_core.models import ExportResult
from smartswitch_core.path_safety import safe_output_path


class AppDataPasswordError(ValueError):
    """The Android backup master key could not be unlocked."""


class AppApkDecryptionError(ValueError):
    """The legacy Smart Switch APK key did not decrypt a PENC payload."""


_PENC_ENCRYPTED_PREFIX_BYTES = 1024 * 1024
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
                    normalized = "".join(
                        char for char in str(key).lower() if char.isalnum()
                    )
                    if (
                        normalized in _PASSWORD_FIELD_NAMES
                        and isinstance(child, str)
                        and child
                    ):
                        source = f"{metadata_path.name}:{key}"
                        if normalized == "dummy" and len(child) == 64:
                            try:
                                decoded = bytes.fromhex(child).decode("utf-8")
                            except (UnicodeDecodeError, ValueError):
                                pass
                            else:
                                if all(char in string.printable for char in decoded):
                                    candidates.append(
                                        (f"{source} (hex decoded)", decoded)
                                    )
                        candidates.append((source, child))
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(metadata)
    return candidates


def _application_credential_candidates(
    backup_dir: Path,
    *,
    supplied_password: str | None,
    fallback_password: str,
    include_empty: bool = False,
) -> list[SessionCredential]:
    candidates: list[SessionCredential] = []
    if supplied_password is not None:
        candidates.append(SessionCredential(supplied_password, "Export Options"))
    try:
        candidates.append(load_session_credential(backup_dir))
    except SessionCredentialError:
        pass
    candidates.extend(
        SessionCredential(value, source)
        for source, value in _metadata_password_candidates(backup_dir)
    )
    candidates.append(SessionCredential(fallback_password, "Smart Switch legacy key"))
    if include_empty:
        candidates.append(SessionCredential("", "empty password"))

    deduplicated: list[SessionCredential] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.value in seen:
            continue
        seen.add(candidate.value)
        deduplicated.append(candidate)
    return deduplicated


def _safe_join(root: Path, relative_name: str) -> Path:
    return safe_output_path(root, relative_name)


def _decrypt_penc(path: Path, dummy: str) -> bytes:
    raw = path.read_bytes()
    if len(raw) < 20:
        raise ValueError(".penc file too small")

    encrypted_size = int.from_bytes(raw[:4], "big")
    if (
        encrypted_size <= 0
        or encrypted_size > _PENC_ENCRYPTED_PREFIX_BYTES + AES.block_size
    ):
        raise ValueError(f"Invalid .penc encrypted segment size: {encrypted_size}")
    encrypted_end = 4 + encrypted_size
    if encrypted_end > len(raw) or encrypted_size % AES.block_size:
        raise ValueError("Truncated or unaligned .penc encrypted segment")

    encrypted = raw[4:encrypted_end]
    decrypted = AES.new(derive_dummy_key(dummy), AES.MODE_CBC, DEFAULT_PENC_IV).decrypt(
        encrypted
    )
    try:
        prefix = unpad(decrypted, AES.block_size)
    except ValueError as exc:
        raise AppApkDecryptionError(
            "Smart Switch backup dummy key was rejected"
        ) from exc
    suffix = raw[encrypted_end:]
    if suffix and len(prefix) != _PENC_ENCRYPTED_PREFIX_BYTES:
        raise AppApkDecryptionError("Smart Switch backup dummy key was rejected")

    apk = prefix + suffix
    try:
        _validate_apk(apk)
    except ValueError as exc:
        raise AppApkDecryptionError(
            "Smart Switch backup dummy key was rejected"
        ) from exc
    return apk


def _validate_zip_members(members: list[zipfile.ZipInfo]) -> ArchiveBudget:
    budget = ArchiveBudget(max_bytes=MAX_APK_OUTPUT_BYTES)
    for member in members:
        budget.add(member.file_size if not member.is_dir() else 0)
    return budget


def _validate_apk(data: bytes) -> dict[str, object]:
    if not data.startswith(b"PK\x03\x04"):
        raise ValueError("Decrypted .penc does not have ZIP magic")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            _validate_zip_members(members)
            names = {member.filename for member in members}
            if archive.testzip() is not None:
                raise ValueError("Decrypted APK failed a ZIP CRC check")
    except (ArchiveLimitError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise ValueError(f"Decrypted .penc archive was rejected: {exc}") from exc

    if "AndroidManifest.xml" not in names:
        raise ValueError("Decrypted ZIP is missing AndroidManifest.xml")
    dex_files = sorted(
        name
        for name in names
        if name == "classes.dex" or name.startswith("classes") and name.endswith(".dex")
    )
    if "classes.dex" not in dex_files:
        raise ValueError("Decrypted APK is missing classes.dex")
    return {
        "zip_entries": len(names),
        "zip_crc": "valid",
        "android_manifest": True,
        "dex_files": len(dex_files),
    }


def _decode_penc_with_candidates(
    path: Path,
    backup_dir: Path,
    *,
    supplied_password: str | None,
    fallback_password: str,
) -> tuple[bytes, str]:
    candidates = _application_credential_candidates(
        backup_dir,
        supplied_password=supplied_password,
        fallback_password=fallback_password,
    )
    for candidate in candidates:
        try:
            return _decrypt_penc(path, candidate.value), candidate.source
        except AppApkDecryptionError:
            continue

    raise AppApkDecryptionError(
        "None of the available Smart Switch credentials produced a valid APK. "
        "Export Application APKs to preserve the raw PENC file."
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
        members = archive.infolist()
        try:
            budget = _validate_zip_members(members)
            DiskSpaceGuard(out_dir).consume(budget.bytes)
        except ArchiveLimitError as exc:
            file_count = sum(not member.is_dir() for member in members)
            return 0, file_count, [f"PENC recovery refused the archive: {exc}"]
        for member in members:
            if member.is_dir():
                continue
            target: Path | None = None
            try:
                member_type = stat.S_IFMT(member.external_attr >> 16)
                if member_type and member_type != stat.S_IFREG:
                    raise ValueError("Unsupported ZIP member type")
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

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        try:
            budget = _validate_zip_members(members)
            DiskSpaceGuard(out_dir).consume(budget.bytes)
        except ArchiveLimitError as exc:
            file_count = sum(not member.is_dir() for member in members)
            return 0, file_count, [f"Refused to extract ZIP archive: {exc}"]
        for info in members:
            try:
                target = _safe_join(out_dir, info.filename)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                member_type = stat.S_IFMT(info.external_attr >> 16)
                if member_type and member_type != stat.S_IFREG:
                    skipped += 1
                    warnings.append("Skipped unsupported ZIP member type")
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as handle:
                    shutil.copyfileobj(source, handle)
                extracted += 1
            except (OSError, RuntimeError, ValueError, zipfile.BadZipFile):
                skipped += 1
                warnings.append("Failed to extract a ZIP member")

    return extracted, skipped, warnings


def _split_android_backup_header(
    raw: bytes, n_lines: int = 9
) -> tuple[list[bytes], int]:
    lines: list[bytes] = []
    pos = 0
    for _ in range(n_lines):
        nl = raw.find(b"\n", pos)
        if nl == -1:
            raise ValueError("Truncated Android backup header")
        lines.append(raw[pos:nl].rstrip(b"\r"))
        pos = nl + 1
    return lines, pos


def _decode_data_payload(
    path: Path,
    password: str,
    output_path: Path,
) -> AndroidBackupMetadata:
    return decode_android_backup_to_tar(path, password, output_path)


def _decode_data_with_candidates(
    path: Path,
    backup_dir: Path,
    output_path: Path,
    *,
    supplied_password: str | None,
    fallback_password: str,
) -> AndroidBackupMetadata:
    candidates = _application_credential_candidates(
        backup_dir,
        supplied_password=supplied_password,
        fallback_password=fallback_password,
        include_empty=True,
    )

    last_credential_error: AndroidBackupDecodeError | None = None
    for candidate in candidates:
        try:
            meta = _decode_data_payload(path, candidate.value, output_path)
        except AndroidBackupDecodeError as exc:
            if exc.phase in _CREDENTIAL_FAILURE_PHASES:
                last_credential_error = exc
                continue
            raise
        meta["password_source"] = candidate.source
        return meta

    raise AppDataPasswordError(
        UNAVAILABLE_CREDENTIAL_MESSAGE
    ) from last_credential_error


def _safe_extract_tar(tar_path: Path, out_dir: Path) -> tuple[int, list[str]]:
    warnings: list[str] = []
    if not tar_path.is_file() or tar_path.stat().st_size == 0:
        return 0, warnings

    out_dir.mkdir(parents=True, exist_ok=True)
    extracted = 0
    budget = ArchiveBudget()
    try:
        DiskSpaceGuard(out_dir).consume(tar_path.stat().st_size)
    except ArchiveLimitError as exc:
        return 0, [f"Refused to extract TAR archive: {exc}"]
    try:
        with tarfile.open(tar_path, mode="r:") as tf:
            for member in tf:
                try:
                    budget.add(member.size if member.isfile() else 0)
                except ArchiveLimitError as exc:
                    warnings.append(
                        f"Stopped TAR extraction at the resource limit: {exc}"
                    )
                    break
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
                target.parent.mkdir(parents=True, exist_ok=True)
                source = tf.extractfile(member)
                if source is None:
                    continue
                with source, target.open("wb") as handle:
                    shutil.copyfileobj(source, handle, length=1024 * 1024)
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
                    "validation": "ZIP, CRC, AndroidManifest.xml, and classes.dex valid",
                }
                if include_decrypt:
                    dec_path = package_out / f"{package_id}.decrypted.apk"
                    dec_path.write_bytes(dec)
                    outputs.append(dec_path)
                if include_extract:
                    files_dir = package_out / "apk_files"
                    extracted, skipped, local_warnings = _extract_local_entries(
                        dec, files_dir
                    )
                    warnings.extend(local_warnings)
                    outputs.append(files_dir)
                    manifest["penc"]["extracted_files"] = extracted
                    manifest["penc"]["skipped_files"] = skipped
            except AppApkDecryptionError as exc:
                errors.append(f"APK decrypt/extract failed for {package_id}: {exc}")
                if include_extract:
                    recovered_dir = package_out / "apk_recovered_files"
                    recovered, failed, recovery_warnings = (
                        _extract_recoverable_penc_entries(
                            penc_path,
                            recovered_dir,
                        )
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
                with TemporaryDirectory(
                    prefix=".smartswitch-data-",
                    dir=package_out,
                ) as temporary_directory:
                    decoded_tar = Path(temporary_directory) / "decoded.tar"
                    meta = _decode_data_with_candidates(
                        data_path,
                        backup_dir,
                        decoded_tar,
                        supplied_password=app_data_password,
                        fallback_password=dummy_hex,
                    )
                    manifest["data"] = meta
                    if include_extract:
                        data_dir = package_out / "data_files"
                        extracted, local_warnings = _safe_extract_tar(
                            decoded_tar, data_dir
                        )
                        warnings.extend(local_warnings)
                        manifest["data"]["extracted_files"] = extracted
                        outputs.append(data_dir)
                    if include_decrypt:
                        tar_path = package_out / "data.decoded.tar"
                        decoded_tar.replace(tar_path)
                        outputs.append(tar_path)
            except Exception as exc:  # pragma: no cover - defensive boundary
                errors.append(f"Data decode/extract failed for {package_id}: {exc}")
        else:
            warnings.append(f"Missing .data file for {package_id}")

    manifest_path = package_out / manifest_name
    write_manifest(manifest_path, manifest)
    outputs.append(manifest_path)

    return ExportResult(
        ok=not errors, outputs=outputs, warnings=warnings, errors=errors
    )


def copy_app_apk_payload(
    package_id: str, backup_dir: Path, out_dir: Path
) -> ExportResult:
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
    return ExportResult(
        ok=not errors, outputs=outputs, warnings=warnings, errors=errors
    )

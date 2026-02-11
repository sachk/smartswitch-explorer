from __future__ import annotations

import json
import struct
import tarfile
import zlib
from pathlib import Path

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from smartswitch_core.crypto.common import DEFAULT_DUMMY_HEX, DEFAULT_PENC_IV, derive_dummy_key
from smartswitch_core.export import write_manifest
from smartswitch_core.models import ExportResult


def _safe_join(root: Path, relative_name: str) -> Path:
    safe_rel = Path(relative_name.replace("\\", "/")).as_posix().lstrip("/")
    candidate = (root / safe_rel).resolve()
    root_resolved = root.resolve()
    if not str(candidate).startswith(str(root_resolved)):
        raise ValueError("Unsafe output path")
    return candidate


def _decrypt_penc(path: Path, dummy_hex: str) -> bytes:
    raw = path.read_bytes()
    if len(raw) < 20:
        raise ValueError(".penc file too small")
    ct = raw[4:]
    ct = ct[: len(ct) - (len(ct) % 16)]
    if not ct:
        raise ValueError("No aligned ciphertext in .penc")
    return AES.new(derive_dummy_key(dummy_hex), AES.MODE_CBC, DEFAULT_PENC_IV).decrypt(ct)


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
    raw = path.read_bytes()
    lines, payload_offset = _split_android_backup_header(raw)
    if lines[0] != b"ANDROID BACKUP":
        raise ValueError("Not an Android backup data file")

    version = lines[1].decode("ascii", "replace")
    compressed = int(lines[2].decode("ascii"))
    algorithm = lines[3].decode("ascii", "replace")
    user_salt = bytes.fromhex(lines[4].decode("ascii"))
    rounds = int(lines[6].decode("ascii"))
    user_iv = bytes.fromhex(lines[7].decode("ascii"))
    mk_blob = bytes.fromhex(lines[8].decode("ascii"))

    if algorithm != "AES-256":
        raise ValueError(f"Unsupported algorithm: {algorithm}")

    user_key = __import__("hashlib").pbkdf2_hmac(
        "sha1", password.encode("utf-8"), user_salt, rounds, dklen=32
    )
    unwrapped = unpad(AES.new(user_key, AES.MODE_CBC, user_iv).decrypt(mk_blob), 16)

    iv_len = unwrapped[0]
    cursor = 1
    mk_iv = unwrapped[cursor : cursor + iv_len]
    cursor += iv_len
    mk_len = unwrapped[cursor]
    cursor += 1
    mk = unwrapped[cursor : cursor + mk_len]

    payload_enc = raw[payload_offset:]
    if not payload_enc:
        payload = b""
    else:
        if len(payload_enc) % 16:
            raise ValueError("Encrypted payload not AES aligned")
        payload = unpad(AES.new(mk, AES.MODE_CBC, mk_iv).decrypt(payload_enc), 16)
        if compressed:
            payload = zlib.decompress(payload)

    meta = {
        "version": version,
        "compressed": compressed,
        "algorithm": algorithm,
        "payload_len": len(payload),
    }
    return payload, meta


def _safe_extract_tar(payload: bytes, out_dir: Path) -> tuple[int, list[str]]:
    warnings: list[str] = []
    if not payload:
        return 0, warnings

    out_dir.mkdir(parents=True, exist_ok=True)
    extracted = 0
    try:
        with tarfile.open(fileobj=__import__("io").BytesIO(payload), mode="r:") as tf:
            for member in tf.getmembers():
                try:
                    target = _safe_join(out_dir, member.name)
                except ValueError:
                    warnings.append(f"Skipped unsafe tar member: {member.name}")
                    continue
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
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
    include_decrypt: bool = True,
    include_extract: bool = True,
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
                dec = _decrypt_penc(penc_path, dummy_hex)
                if include_decrypt:
                    dec_path = package_out / "penc.decrypted.bin"
                    dec_path.write_bytes(dec)
                    outputs.append(dec_path)
                if include_extract:
                    files_dir = package_out / "apk_files"
                    extracted, skipped, local_warnings = _extract_local_entries(dec, files_dir)
                    warnings.extend(local_warnings)
                    outputs.append(files_dir)
                    manifest["penc"] = {
                        "decrypted_size": len(dec),
                        "extracted_files": extracted,
                        "skipped_files": skipped,
                    }
            except Exception as exc:  # pragma: no cover - defensive boundary
                errors.append(f"APK decrypt/extract failed for {package_id}: {exc}")
        else:
            warnings.append(f"Missing .penc file for {package_id}")

    if mode in {"data", "both"}:
        data_path = apk_dir / f"{package_id}.data"
        if data_path.exists():
            try:
                payload, meta = _decode_data_payload(data_path, dummy_hex)
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

    manifest_path = package_out / "manifest.json"
    write_manifest(manifest_path, manifest)
    outputs.append(manifest_path)

    return ExportResult(ok=not errors, outputs=outputs, warnings=warnings, errors=errors)

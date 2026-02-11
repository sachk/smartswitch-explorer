from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path, PurePosixPath

from Crypto.Cipher import AES

from smartswitch_core.crypto.common import DEFAULT_DUMMY_HEX, derive_dummy_key
from smartswitch_core.export import write_manifest
from smartswitch_core.models import ExportResult


class MessageSource:
    def __init__(self, backup_dir: Path) -> None:
        self.message_dir = backup_dir / "MESSAGE"
        self.smem_path = self.message_dir / "Message.smem"

    def _local_files(self) -> list[Path]:
        if not self.message_dir.exists():
            return []
        return [p for p in self.message_dir.iterdir() if p.is_file()]

    def _zip_infos(self) -> list[zipfile.ZipInfo]:
        if not self.smem_path.exists() or not zipfile.is_zipfile(self.smem_path):
            return []
        try:
            with zipfile.ZipFile(self.smem_path) as zf:
                return list(zf.infolist())
        except (OSError, zipfile.BadZipFile):
            return []

    def read_first(self, predicate: callable) -> tuple[str, bytes] | None:
        for path in self._local_files():
            if predicate(path.name):
                try:
                    return path.name, path.read_bytes()
                except OSError:
                    continue

        infos = self._zip_infos()
        if not infos:
            return None
        try:
            with zipfile.ZipFile(self.smem_path) as zf:
                for info in infos:
                    name = PurePosixPath(info.filename).name
                    if predicate(name):
                        return name, zf.read(info)
        except (OSError, zipfile.BadZipFile, KeyError):
            return None
        return None

    def copy_matching(self, predicate: callable, destination: Path) -> int:
        destination.mkdir(parents=True, exist_ok=True)
        copied = 0
        used_names: set[str] = set()

        def unique_name(name: str) -> str:
            if name not in used_names:
                used_names.add(name)
                return name
            base = Path(name).stem
            ext = Path(name).suffix
            index = 1
            while True:
                candidate = f"{base}_{index}{ext}"
                if candidate not in used_names:
                    used_names.add(candidate)
                    return candidate
                index += 1

        for path in self._local_files():
            if not predicate(path.name):
                continue
            try:
                target_name = unique_name(path.name)
                shutil.copy2(path, destination / target_name)
                copied += 1
            except OSError:
                continue

        infos = self._zip_infos()
        if not infos:
            return copied

        try:
            with zipfile.ZipFile(self.smem_path) as zf:
                for info in infos:
                    name = PurePosixPath(info.filename).name
                    if not predicate(name):
                        continue
                    target_name = unique_name(name)
                    (destination / target_name).write_bytes(zf.read(info))
                    copied += 1
        except (OSError, zipfile.BadZipFile, KeyError):
            return copied

        return copied


def _decrypt_bk_json(raw: bytes, dummy_hex: str) -> list[dict] | dict:
    if len(raw) < 32 or (len(raw) - 16) % 16 != 0:
        raise ValueError("Invalid backup block layout")
    key = derive_dummy_key(dummy_hex)
    iv = raw[:16]
    ciphertext = raw[16:]
    decrypted = AES.new(key, AES.MODE_CBC, iv).decrypt(ciphertext)

    start_array = decrypted.find(b"[")
    start_obj = decrypted.find(b"{")
    starts = [x for x in (start_array, start_obj) if x != -1]
    if not starts:
        raise ValueError("JSON start not found")
    start = min(starts)
    end = max(decrypted.rfind(b"]"), decrypted.rfind(b"}"))
    if end == -1 or end < start:
        raise ValueError("JSON end not found")

    payload = decrypted[start : end + 1]
    return json.loads(payload.decode("utf-8"))


def decode_and_export_messages(
    backup_dir: Path,
    out_dir: Path,
    selected_parts: set[str],
    *,
    dummy_hex: str = DEFAULT_DUMMY_HEX,
    include_decrypt: bool = True,
    include_extract: bool = True,
) -> ExportResult:
    outputs: list[Path] = []
    warnings: list[str] = []
    errors: list[str] = []

    source = MessageSource(backup_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    message_out = out_dir / "messages"
    message_out.mkdir(parents=True, exist_ok=True)

    manifest = {
        "selected_parts": sorted(selected_parts),
        "decoded": {},
        "copied": {},
        "warnings": warnings,
        "errors": errors,
    }

    if "sms" in selected_parts and include_decrypt:
        sms_entry = source.read_first(lambda name: name.endswith("sms_restore.bk"))
        if sms_entry is None:
            warnings.append("sms_restore.bk not found")
        else:
            _, raw = sms_entry
            try:
                sms_json = _decrypt_bk_json(raw, dummy_hex)
                sms_path = message_out / "sms.json"
                sms_path.write_text(json.dumps(sms_json, ensure_ascii=False, indent=2), encoding="utf-8")
                outputs.append(sms_path)
                manifest["decoded"]["sms"] = len(sms_json) if isinstance(sms_json, list) else 1
            except (ValueError, json.JSONDecodeError) as exc:
                warnings.append(f"SMS decode failed: {exc}")

    if "mms" in selected_parts and include_decrypt:
        mms_entry = source.read_first(lambda name: name.endswith("mms_restore.bk"))
        if mms_entry is None:
            warnings.append("mms_restore.bk not found")
        else:
            _, raw = mms_entry
            try:
                mms_json = _decrypt_bk_json(raw, dummy_hex)
                mms_path = message_out / "mms.json"
                mms_path.write_text(json.dumps(mms_json, ensure_ascii=False, indent=2), encoding="utf-8")
                outputs.append(mms_path)
                manifest["decoded"]["mms"] = len(mms_json) if isinstance(mms_json, list) else 1
            except (ValueError, json.JSONDecodeError) as exc:
                warnings.append(f"MMS decode failed: {exc}")

    if include_extract and "attachments" in selected_parts:
        media_dir = message_out / "media"
        copied = source.copy_matching(lambda name: "PART_" in name, media_dir)
        manifest["copied"]["attachments"] = copied
        if copied:
            outputs.append(media_dir)

    if include_extract and "rcs" in selected_parts:
        rcs_dir = message_out / "rcs"
        copied = source.copy_matching(
            lambda name: ("RCSMESSAGE" in name) or ("RcsMessage" in name),
            rcs_dir,
        )
        manifest["copied"]["rcs"] = copied
        if copied:
            outputs.append(rcs_dir)

    manifest_path = message_out / "manifest.json"
    write_manifest(manifest_path, manifest)
    outputs.append(manifest_path)

    ok = not errors
    return ExportResult(ok=ok, outputs=outputs, warnings=warnings, errors=errors)

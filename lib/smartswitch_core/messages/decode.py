from __future__ import annotations

import csv
from collections.abc import Callable
import io
import json
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from smartswitch_core.crypto.common import DEFAULT_DUMMY_HEX
from smartswitch_core.crypto.smartdecrypt import decode_iv_prefix_payload
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

    def read_first(self, predicate: Callable[[str], bool]) -> tuple[str, bytes] | None:
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

    def copy_matching(self, predicate: Callable[[str], bool], destination: Path) -> int:
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


def _decrypt_bk_json(
    raw: bytes,
    dummy_hex: str,
    backup_password: str | None,
) -> list[dict] | dict:
    decoded = decode_iv_prefix_payload(
        raw,
        dummy_hex=dummy_hex,
        password=backup_password,
        name_hint="sms_restore.bk",
    )
    if decoded.kind != "json":
        raise ValueError("Decrypted payload is not JSON")
    return json.loads(decoded.payload.decode("utf-8"))


def _write_rows_csv(payload: list[dict] | dict, target: Path) -> None:
    if isinstance(payload, dict):
        payload = [payload]

    rows = [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []
    if not rows:
        target.write_text("payload\n", encoding="utf-8")
        return

    columns: list[str] = []
    for row in rows:
        for key in row.keys():
            name = str(key)
            if name not in columns:
                columns.append(name)

    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in columns})


def _sqlite_value(value: object) -> object:
    if isinstance(value, bytes):
        return value.hex()
    return value


def _decode_edb_tables(
    raw: bytes,
    dummy_hex: str,
    backup_password: str | None,
) -> dict[str, list[dict[str, object]]]:
    decoded = decode_iv_prefix_payload(
        raw,
        dummy_hex=dummy_hex,
        password=backup_password,
        name_hint="RcsMessage.edb",
    )
    if decoded.kind != "zip":
        raise ValueError("Decrypted EDB payload is not a ZIP archive")

    try:
        with zipfile.ZipFile(io.BytesIO(decoded.payload)) as archive:
            db_info = next(
                (
                    info
                    for info in archive.infolist()
                    if not info.is_dir() and PurePosixPath(info.filename).name == "mmssms.db"
                ),
                None,
            )
            if db_info is None:
                raise ValueError("Decrypted EDB archive does not contain mmssms.db")
            database = archive.read(db_info)
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise ValueError(f"Invalid decrypted EDB archive: {exc}") from exc

    tables: dict[str, list[dict[str, object]]] = {}
    with tempfile.TemporaryDirectory(prefix="smartswitch-messages-") as temp_dir:
        db_path = Path(temp_dir) / "mmssms.db"
        db_path.write_bytes(database)
        try:
            connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            try:
                existing = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                for table_name in ("im", "ft"):
                    if table_name not in existing:
                        continue
                    rows = connection.execute(f'SELECT * FROM "{table_name}"')
                    tables[table_name] = [
                        {key: _sqlite_value(row[key]) for key in row.keys()} for row in rows
                    ]
            finally:
                connection.close()
        except sqlite3.DatabaseError as exc:
            raise ValueError(f"Invalid mmssms.db database: {exc}") from exc

    if not tables:
        raise ValueError("mmssms.db does not contain RCS message tables")
    return tables


def _write_edb_tables(
    tables: dict[str, list[dict[str, object]]],
    destination: Path,
    output_format: str,
) -> list[Path]:
    if output_format == "json":
        target = destination / "rcs.json"
        target.write_text(json.dumps(tables, ensure_ascii=False, indent=2), encoding="utf-8")
        return [target]

    outputs: list[Path] = []
    for table_name, rows in tables.items():
        target = destination / f"rcs_{table_name}.csv"
        _write_rows_csv(rows, target)
        outputs.append(target)
    return outputs

def decode_and_export_messages(
    backup_dir: Path,
    out_dir: Path,
    selected_parts: set[str],
    *,
    message_format: str = "json",
    dummy_hex: str = DEFAULT_DUMMY_HEX,
    backup_password: str | None = None,
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
    normalized_format = message_format.lower().strip()
    if normalized_format not in {"json", "csv", "native"}:
        warnings.append(f"Unknown message format '{message_format}', defaulting to json")
        normalized_format = "json"

    manifest = {
        "selected_parts": sorted(selected_parts),
        "message_format": normalized_format,
        "decoded": {},
        "copied": {},
        "warnings": warnings,
        "errors": errors,
    }

    if "sms" in selected_parts and normalized_format == "native":
        sms_entry = source.read_first(lambda name: name.endswith("sms_restore.bk"))
        if sms_entry is None:
            warnings.append("sms_restore.bk not found")
        else:
            name, raw = sms_entry
            native_dir = message_out / "native"
            native_dir.mkdir(parents=True, exist_ok=True)
            target = native_dir / Path(name).name
            target.write_bytes(raw)
            outputs.append(target)
            manifest["copied"]["sms_native"] = 1
    elif "sms" in selected_parts and include_decrypt:
        sms_entry = source.read_first(lambda name: name.endswith("sms_restore.bk"))
        if sms_entry is None:
            warnings.append("sms_restore.bk not found")
        else:
            _, raw = sms_entry
            try:
                sms_json = _decrypt_bk_json(raw, dummy_hex, backup_password)
                sms_path = message_out / ("sms.csv" if normalized_format == "csv" else "sms.json")
                if normalized_format == "csv":
                    _write_rows_csv(sms_json, sms_path)
                else:
                    sms_path.write_text(json.dumps(sms_json, ensure_ascii=False, indent=2), encoding="utf-8")
                outputs.append(sms_path)
                manifest["decoded"]["sms"] = len(sms_json) if isinstance(sms_json, list) else 1
            except (ValueError, json.JSONDecodeError) as exc:
                warnings.append(f"SMS decode failed: {exc}")

    if "mms" in selected_parts and normalized_format == "native":
        mms_entry = source.read_first(lambda name: name.endswith("mms_restore.bk"))
        if mms_entry is None:
            warnings.append("mms_restore.bk not found")
        else:
            name, raw = mms_entry
            native_dir = message_out / "native"
            native_dir.mkdir(parents=True, exist_ok=True)
            target = native_dir / Path(name).name
            target.write_bytes(raw)
            outputs.append(target)
            manifest["copied"]["mms_native"] = 1
    elif "mms" in selected_parts and include_decrypt:
        mms_entry = source.read_first(lambda name: name.endswith("mms_restore.bk"))
        if mms_entry is None:
            warnings.append("mms_restore.bk not found")
        else:
            _, raw = mms_entry
            try:
                mms_json = _decrypt_bk_json(raw, dummy_hex, backup_password)
                mms_path = message_out / ("mms.csv" if normalized_format == "csv" else "mms.json")
                if normalized_format == "csv":
                    _write_rows_csv(mms_json, mms_path)
                else:
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

    if "rcs" in selected_parts:
        if normalized_format == "native":
            rcs_dir = message_out / "native"
            copied = source.copy_matching(
                lambda name: ("RCSMESSAGE" in name) or ("RcsMessage" in name),
                rcs_dir,
            )
            manifest["copied"]["rcs_native"] = copied
            if copied:
                outputs.append(rcs_dir)
        elif include_decrypt:
            rcs_entry = source.read_first(
                lambda name: (
                    (("RCSMESSAGE" in name) or ("RcsMessage" in name))
                    and name.lower().endswith(".edb")
                )
            )
            if rcs_entry is None:
                warnings.append("RcsMessage.edb not found")
            else:
                _, raw = rcs_entry
                try:
                    tables = _decode_edb_tables(raw, dummy_hex, backup_password)
                    converted = _write_edb_tables(tables, message_out, normalized_format)
                    outputs.extend(converted)
                    manifest["decoded"]["rcs"] = {
                        table_name: len(rows) for table_name, rows in tables.items()
                    }
                except ValueError as exc:
                    warnings.append(f"RCS message decode failed: {exc}")

    manifest_path = message_out / "manifest.json"
    write_manifest(manifest_path, manifest)
    outputs.append(manifest_path)

    ok = not errors
    return ExportResult(ok=ok, outputs=outputs, warnings=warnings, errors=errors)

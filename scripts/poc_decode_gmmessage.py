#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_FILE_RE = re.compile(r"_size_(?P<size>\d+)_id_(?P<id>\d+)$")


@dataclass(slots=True)
class DecodeStats:
    parsed_messages: int = 0
    parse_errors: int = 0
    base64_errors: int = 0


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise ValueError("unexpected EOF while reading varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return value, offset
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")


def _is_printable_text(data: bytes) -> bool:
    if not data:
        return False
    if any(b == 0 for b in data):
        return False
    return all((32 <= b <= 126) or b in (9, 10, 13) for b in data)


def _parse_message(data: bytes, depth: int, stats: DecodeStats) -> list[dict[str, Any]]:
    offset = 0
    fields: list[dict[str, Any]] = []
    while offset < len(data):
        key, offset = _read_varint(data, offset)
        field_number = key >> 3
        wire_type = key & 0x07
        if field_number <= 0:
            raise ValueError("invalid field number")

        entry: dict[str, Any] = {"field": field_number, "wire_type": wire_type}
        if wire_type == 0:
            value, offset = _read_varint(data, offset)
            entry["value"] = value
        elif wire_type == 1:
            end = offset + 8
            if end > len(data):
                raise ValueError("unexpected EOF for fixed64")
            value = int.from_bytes(data[offset:end], "little")
            offset = end
            entry["value"] = value
        elif wire_type == 2:
            length, offset = _read_varint(data, offset)
            end = offset + length
            if end > len(data):
                raise ValueError("unexpected EOF for length-delimited field")
            chunk = data[offset:end]
            offset = end
            value: dict[str, Any] = {"length": len(chunk), "base64": base64.b64encode(chunk).decode("ascii")}
            if _is_printable_text(chunk):
                value["text"] = chunk.decode("utf-8", errors="replace")
            elif len(chunk) <= 32:
                value["hex"] = chunk.hex()

            if depth < 3 and chunk:
                try:
                    nested = _parse_message(chunk, depth + 1, stats)
                    if nested:
                        value["nested"] = nested
                except ValueError:
                    pass
            entry["value"] = value
        elif wire_type == 5:
            end = offset + 4
            if end > len(data):
                raise ValueError("unexpected EOF for fixed32")
            value = int.from_bytes(data[offset:end], "little")
            offset = end
            entry["value"] = value
        else:
            raise ValueError(f"unsupported wire type {wire_type}")
        fields.append(entry)
    stats.parsed_messages += 1
    return fields


def _guess_payload_type(path: Path) -> str:
    head = path.read_bytes()[:16]
    if head.startswith(b"\xFF\xD8\xFF"):
        return "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1A\n"):
        return "png"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "mp4"
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return "gif"
    if head.startswith(b"BEGIN:VCARD"):
        return "vcard"
    if head.startswith(b"\x1A\x45\xDF\xA3"):
        return "webm"
    if head.startswith(b"PK\x03\x04"):
        return "zip"
    if head.startswith(b"SQLite format 3"):
        return "sqlite"
    return "unknown"


def _parse_name(name: str) -> dict[str, int] | None:
    match = _FILE_RE.search(name)
    if not match:
        return None
    return {"id": int(match.group("id")), "size": int(match.group("size"))}


def decode_gmmessage(backup_dir: Path, output_path: Path) -> dict[str, Any]:
    gm_dir = backup_dir / "GMMESSAGE"
    info_path = gm_dir / "d2d_item_info.json"
    if not info_path.exists():
        raise FileNotFoundError(f"Missing metadata file: {info_path}")

    payload_files = {p.name: p for p in gm_dir.iterdir() if p.is_file() and p.name != "d2d_item_info.json"}
    payload_type_counts: Counter[str] = Counter()
    stats = DecodeStats()

    raw = json.loads(info_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Expected d2d_item_info.json to be a JSON array")

    decoded_entries: list[dict[str, Any]] = []
    missing_payload_count = 0
    id_mismatch_count = 0

    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            decoded_entries.append({"index": index, "error": "entry is not an object"})
            continue

        name = str(item.get("a", ""))
        item_id = item.get("b")
        encoded = item.get("c")
        file_path = payload_files.get(name)

        file_info: dict[str, Any] = {"exists": file_path is not None}
        name_info = _parse_name(name)
        if name_info:
            file_info["name_id"] = name_info["id"]
            file_info["name_size"] = name_info["size"]

        if file_path is None:
            missing_payload_count += 1
        else:
            size = file_path.stat().st_size
            kind = _guess_payload_type(file_path)
            file_info["size"] = size
            file_info["type"] = kind
            payload_type_counts[kind] += 1
            if name_info and name_info["size"] != size:
                file_info["size_mismatch"] = True

        if isinstance(item_id, int) and name_info and item_id != name_info["id"]:
            id_mismatch_count += 1

        meta: dict[str, Any] = {"base64_length": len(encoded) if isinstance(encoded, str) else None}
        if isinstance(encoded, str):
            try:
                normalized = "".join(encoded.split())
                blob = base64.b64decode(normalized)
                meta["decoded_length"] = len(blob)
                try:
                    meta["protobuf"] = _parse_message(blob, depth=0, stats=stats)
                except ValueError as exc:
                    stats.parse_errors += 1
                    meta["protobuf_error"] = str(exc)
                    meta["raw_hex"] = blob.hex()
            except Exception as exc:  # noqa: BLE001
                stats.base64_errors += 1
                meta["base64_error"] = str(exc)

        decoded_entries.append(
            {
                "index": index,
                "name": name,
                "id": item_id,
                "file": file_info,
                "meta": meta,
            }
        )

    output: dict[str, Any] = {
        "format": "smart_switch_gmmessage_poc_v1",
        "backup_dir": str(backup_dir),
        "gmmessage_dir": str(gm_dir),
        "source_metadata": str(info_path),
        "summary": {
            "metadata_entries": len(raw),
            "payload_files": len(payload_files),
            "missing_payload_files": missing_payload_count,
            "id_mismatch_count": id_mismatch_count,
            "protobuf_messages_parsed": stats.parsed_messages,
            "protobuf_parse_errors": stats.parse_errors,
            "base64_decode_errors": stats.base64_errors,
            "payload_type_counts": dict(payload_type_counts.most_common()),
        },
        "entries": decoded_entries,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def _default_output_path(backup_dir: Path) -> Path:
    return backup_dir.parent / "analysis" / f"{backup_dir.name}_gmmessage_poc.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PoC decoder for Smart Switch GMMESSAGE backups to JSON."
    )
    parser.add_argument("backup_dir", type=Path, help="Path to backup root containing GMMESSAGE/")
    parser.add_argument("--out", type=Path, default=None, help="Output JSON path")
    args = parser.parse_args()

    backup_dir = args.backup_dir.expanduser().resolve()
    out = args.out.expanduser().resolve() if args.out else _default_output_path(backup_dir)

    result = decode_gmmessage(backup_dir, out)
    summary = result["summary"]
    print(f"Wrote: {out}")
    print(
        "Summary: "
        f"entries={summary['metadata_entries']}, "
        f"payload_files={summary['payload_files']}, "
        f"missing_payload_files={summary['missing_payload_files']}, "
        f"protobuf_parse_errors={summary['protobuf_parse_errors']}"
    )
    print(f"Payload types: {summary['payload_type_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from dataclasses import dataclass

from Crypto.Cipher import AES

from smartswitch_core.crypto.common import DEFAULT_DUMMY_HEX, derive_dummy_key


@dataclass(slots=True)
class DecodedPayload:
    payload: bytes
    kind: str
    extension: str


_KIND_TO_EXTENSION = {
    "json": ".json",
    "xml": ".xml",
    "zip": ".zip",
    "sqlite": ".db",
    "png": ".png",
    "jpeg": ".jpg",
    "webp": ".webp",
    "mp3": ".mp3",
    "text": ".txt",
    "binary": ".bin",
}


def decrypt_iv_prefix_aes_cbc(raw: bytes, *, dummy_hex: str = DEFAULT_DUMMY_HEX) -> bytes:
    if len(raw) < 32:
        raise ValueError("Encrypted payload too small")
    iv = raw[:16]
    ciphertext = raw[16:]
    ciphertext = ciphertext[: len(ciphertext) - (len(ciphertext) % 16)]
    if not ciphertext:
        raise ValueError("Encrypted payload has no aligned ciphertext")
    return AES.new(derive_dummy_key(dummy_hex), AES.MODE_CBC, iv).decrypt(ciphertext)


def _decrypt_with_suffix_trim(raw: bytes, *, dummy_hex: str, trim_tail_bytes: int) -> bytes:
    if len(raw) < 32:
        raise ValueError("Encrypted payload too small")
    iv = raw[:16]
    tail = raw[16:]
    if trim_tail_bytes:
        if len(tail) <= trim_tail_bytes:
            raise ValueError("Encrypted payload tail is too short")
        tail = tail[:-trim_tail_bytes]
    ciphertext = tail[: len(tail) - (len(tail) % 16)]
    if not ciphertext:
        raise ValueError("Encrypted payload has no aligned ciphertext")
    return AES.new(derive_dummy_key(dummy_hex), AES.MODE_CBC, iv).decrypt(ciphertext)


def extract_json_region(payload: bytes) -> bytes:
    start_array = payload.find(b"[")
    start_obj = payload.find(b"{")
    starts = [x for x in (start_array, start_obj) if x != -1]
    if not starts:
        raise ValueError("JSON start not found")
    start = min(starts)
    end = max(payload.rfind(b"]"), payload.rfind(b"}"))
    if end == -1 or end < start:
        raise ValueError("JSON end not found")
    return payload[start : end + 1]


def extract_xml_region(payload: bytes, *, root_tag: str | None = None) -> bytes:
    start = payload.find(b"<?xml")
    if start == -1:
        if root_tag:
            start = payload.find(f"<{root_tag}".encode("utf-8"))
        if start == -1:
            start = payload.find(b"<")
    if start == -1:
        raise ValueError("XML start not found")

    if root_tag:
        marker = f"</{root_tag}>".encode("utf-8")
        end = payload.rfind(marker)
        if end != -1:
            return payload[start : end + len(marker)]

    end = payload.rfind(b">")
    if end == -1 or end < start:
        raise ValueError("XML end not found")
    return payload[start : end + 1]


def infer_payload_kind(payload: bytes) -> str:
    stripped = payload.lstrip()
    if stripped.startswith((b"{", b"[")):
        return "json"
    if stripped.startswith(b"<?xml") or (stripped.startswith(b"<") and b">" in stripped[:256]):
        return "xml"
    if payload.startswith(b"PK\x03\x04"):
        return "zip"
    if payload.startswith(b"SQLite format 3"):
        return "sqlite"
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if payload.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return "webp"
    if payload.startswith(b"ID3"):
        return "mp3"
    head = payload[:256]
    if head:
        printable = sum(1 for c in head if 32 <= c < 127 or c in (9, 10, 13)) / len(head)
        if printable >= 0.95:
            return "text"
    return "binary"


def normalize_payload(payload: bytes, kind: str, *, xml_root_tag: str | None = None) -> bytes:
    if kind == "json":
        return extract_json_region(payload)
    if kind == "xml":
        return extract_xml_region(payload, root_tag=xml_root_tag)
    if kind == "text":
        clipped = payload.split(b"\x00", 1)[0]
        out = bytearray()
        for byte in clipped:
            if 32 <= byte < 127 or byte in (9, 10, 13):
                out.append(byte)
            else:
                break
        return bytes(out) if out else clipped
    return payload.rstrip(b"\x00")


def is_probably_encrypted_name(name: str) -> bool:
    lower = name.lower()
    return (
        lower.endswith(".enc")
        or lower.endswith(".exml")
        or lower.endswith("encp")
        or lower.endswith(".bk")
        or "encrypted" in lower
        or "_encrypt" in lower
        or "encrypt_" in lower
        or lower.startswith("enc_")
    )


def decode_iv_prefix_payload(
    raw: bytes,
    *,
    dummy_hex: str = DEFAULT_DUMMY_HEX,
    name_hint: str = "",
    xml_root_tag: str | None = None,
) -> DecodedPayload:
    def normalized_kind(candidate: bytes) -> tuple[str, bytes]:
        kind = infer_payload_kind(candidate)
        try:
            normalized = normalize_payload(candidate, kind, xml_root_tag=xml_root_tag)
            return kind, normalized
        except ValueError:
            # If structured extraction fails, keep the decrypted bytes but
            # downgrade the classification so callers can still export data.
            return "binary", candidate.rstrip(b"\x00")

    variants: list[bytes] = []
    errors: list[str] = []
    for trim in (0, 16):
        try:
            variants.append(_decrypt_with_suffix_trim(raw, dummy_hex=dummy_hex, trim_tail_bytes=trim))
        except ValueError as exc:
            errors.append(str(exc))

    if not variants:
        raise ValueError("; ".join(errors) if errors else "Unable to decrypt payload")

    score = {
        "json": 100,
        "xml": 95,
        "zip": 90,
        "sqlite": 85,
        "png": 85,
        "jpeg": 85,
        "webp": 85,
        "mp3": 85,
        "text": 70,
        "binary": 10,
    }
    best_payload = variants[0]
    best_kind, best_norm = normalized_kind(best_payload)
    best_score = score.get(best_kind, 0)

    for candidate in variants:
        kind, normalized = normalized_kind(candidate)
        candidate_score = score.get(kind, 0)
        if candidate_score > best_score or (candidate_score == best_score and len(normalized) > len(best_norm)):
            best_payload = candidate
            best_kind = kind
            best_norm = normalized
            best_score = candidate_score
    if best_kind == "xml" and name_hint.lower().endswith(".exml"):
        extension = ".xml"
    else:
        extension = _KIND_TO_EXTENSION.get(best_kind, ".bin")
    return DecodedPayload(payload=best_norm, kind=best_kind, extension=extension)

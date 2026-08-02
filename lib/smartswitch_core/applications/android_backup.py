from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
import io
from pathlib import Path
import tarfile
import zlib

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from smartswitch_core.crypto.common import DEFAULT_DUMMY_HEX
from smartswitch_core.path_safety import safe_relative_parts


BACKUP_MAGIC = "ANDROID BACKUP"
SUPPORTED_BACKUP_VERSIONS = range(1, 6)
ENCRYPTION_ALGORITHM_AES_256 = "AES-256"
ENCRYPTION_ALGORITHM_NONE = "none"
PBKDF2_KEY_BYTES = 32
PBKDF2_SALT_BYTES = 64
AES_BLOCK_BYTES = 16

UNAVAILABLE_CREDENTIAL_MESSAGE = (
    "Unable to unwrap the master key with the available credential. "
    "The backup may require a different Smart Switch session key or password."
)


class AndroidBackupDecodeError(ValueError):
    def __init__(self, phase: str, message: str) -> None:
        super().__init__(message)
        self.phase = phase


@dataclass(frozen=True, slots=True)
class AndroidBackupHeader:
    magic: str
    version: int
    compressed: bool
    encryption_algorithm: str
    payload_offset: int
    user_salt: bytes = b""
    checksum_salt: bytes = b""
    rounds: int = 0
    user_iv: bytes = b""
    master_key_blob: bytes = b""


@dataclass(frozen=True, slots=True)
class MasterKey:
    iv: bytes
    key: bytes
    user_key_encoding: str
    checksum_encoding: str


@dataclass(slots=True)
class AndroidBackupInspection:
    file_size: int
    sha256: str
    magic: str = ""
    backup_version: int | None = None
    compressed_flag: int | None = None
    encryption_algorithm: str = ""
    user_salt_length: int | None = None
    checksum_salt_length: int | None = None
    pbkdf2_rounds: int | None = None
    user_iv_length: int | None = None
    master_key_blob_length: int | None = None
    master_key_blob_aes_aligned: bool | None = None
    payload_ciphertext_length: int | None = None
    payload_aes_aligned: bool | None = None
    phase: str = "not attempted"
    message: str = ""
    credential_attempts: int = 0
    tar_entries: int | None = None
    details: dict[str, object] = field(default_factory=dict)

    def public_dict(self) -> dict[str, object]:
        return {
            "file size": self.file_size,
            "SHA-256": self.sha256,
            "magic": self.magic,
            "backup version": self.backup_version,
            "compressed flag": self.compressed_flag,
            "encryption algorithm": self.encryption_algorithm,
            "user salt length": self.user_salt_length,
            "master-key checksum salt length": self.checksum_salt_length,
            "PBKDF2 rounds": self.pbkdf2_rounds,
            "user IV length": self.user_iv_length,
            "master-key blob length": self.master_key_blob_length,
            "master-key blob AES aligned": self.master_key_blob_aes_aligned,
            "payload ciphertext length": self.payload_ciphertext_length,
            "payload AES aligned": self.payload_aes_aligned,
            "phase": self.phase,
            "message": self.message,
            "credential attempts": self.credential_attempts,
            "TAR entries": self.tar_entries,
            **self.details,
        }


def _read_header_line(raw: bytes, offset: int) -> tuple[bytes, int]:
    newline = raw.find(b"\n", offset)
    if newline == -1:
        raise AndroidBackupDecodeError("invalid header", "Missing newline in Android Backup header")
    line = raw[offset:newline]
    if line.endswith(b"\r"):
        line = line[:-1]
    return line, newline + 1


def _decode_ascii(line: bytes, field_name: str) -> str:
    try:
        return line.decode("ascii")
    except UnicodeDecodeError as exc:
        raise AndroidBackupDecodeError("invalid header", f"{field_name} is not ASCII") from exc


def _parse_int(line: bytes, field_name: str) -> int:
    text = _decode_ascii(line, field_name)
    if not text or not text.isdecimal():
        raise AndroidBackupDecodeError("invalid header", f"{field_name} is not a decimal integer")
    return int(text)


def _parse_hex(line: bytes, field_name: str) -> bytes:
    text = _decode_ascii(line, field_name)
    if len(text) % 2:
        raise AndroidBackupDecodeError("invalid hexadecimal header field", f"{field_name} has odd length")
    if any(ch not in "0123456789abcdefABCDEF" for ch in text):
        raise AndroidBackupDecodeError("invalid hexadecimal header field", f"{field_name} is not hexadecimal")
    return bytes.fromhex(text)


def parse_android_backup_header(raw: bytes) -> AndroidBackupHeader:
    offset = 0
    magic_raw, offset = _read_header_line(raw, offset)
    magic = _decode_ascii(magic_raw, "magic")
    if magic != BACKUP_MAGIC:
        raise AndroidBackupDecodeError("invalid header", "Invalid Android Backup magic")

    version_raw, offset = _read_header_line(raw, offset)
    version = _parse_int(version_raw, "backup version")
    if version not in SUPPORTED_BACKUP_VERSIONS:
        raise AndroidBackupDecodeError("unsupported format", f"Unsupported Android Backup version: {version}")

    compressed_raw, offset = _read_header_line(raw, offset)
    compressed_text = _decode_ascii(compressed_raw, "compressed flag")
    if compressed_text not in {"0", "1"}:
        raise AndroidBackupDecodeError("invalid header", "Invalid compressed flag")
    compressed = compressed_text == "1"

    algorithm_raw, offset = _read_header_line(raw, offset)
    algorithm = _decode_ascii(algorithm_raw, "encryption algorithm")
    if algorithm == ENCRYPTION_ALGORITHM_NONE:
        return AndroidBackupHeader(
            magic=magic,
            version=version,
            compressed=compressed,
            encryption_algorithm=algorithm,
            payload_offset=offset,
        )
    if algorithm != ENCRYPTION_ALGORITHM_AES_256:
        raise AndroidBackupDecodeError("unsupported format", f"Unsupported encryption algorithm: {algorithm}")

    user_salt_raw, offset = _read_header_line(raw, offset)
    checksum_salt_raw, offset = _read_header_line(raw, offset)
    rounds_raw, offset = _read_header_line(raw, offset)
    user_iv_raw, offset = _read_header_line(raw, offset)
    master_key_blob_raw, offset = _read_header_line(raw, offset)

    user_salt = _parse_hex(user_salt_raw, "user password salt")
    checksum_salt = _parse_hex(checksum_salt_raw, "master-key checksum salt")
    rounds = _parse_int(rounds_raw, "PBKDF2 rounds")
    user_iv = _parse_hex(user_iv_raw, "user key IV")
    master_key_blob = _parse_hex(master_key_blob_raw, "master-key blob")

    if len(user_salt) != PBKDF2_SALT_BYTES or len(checksum_salt) != PBKDF2_SALT_BYTES:
        raise AndroidBackupDecodeError("invalid field length", "Invalid salt length")
    if rounds <= 0:
        raise AndroidBackupDecodeError("invalid field length", "Invalid PBKDF2 rounds")
    if len(user_iv) != AES_BLOCK_BYTES:
        raise AndroidBackupDecodeError("invalid field length", "Invalid user key IV length")
    if not master_key_blob or len(master_key_blob) % AES_BLOCK_BYTES:
        raise AndroidBackupDecodeError("ciphertext not block-aligned", "Master-key blob is not AES block aligned")

    return AndroidBackupHeader(
        magic=magic,
        version=version,
        compressed=compressed,
        encryption_algorithm=algorithm,
        payload_offset=offset,
        user_salt=user_salt,
        checksum_salt=checksum_salt,
        rounds=rounds,
        user_iv=user_iv,
        master_key_blob=master_key_blob,
    )


def _encoding_order(version: int) -> tuple[str, str]:
    if version >= 2:
        return ("utf-8", "legacy-8bit")
    return ("legacy-8bit", "utf-8")


def _password_bytes(password: str, encoding_name: str) -> bytes:
    if encoding_name == "utf-8":
        return password.encode("utf-8")
    if encoding_name == "legacy-8bit":
        return bytes(ord(ch) & 0xFF for ch in password)
    raise ValueError(f"Unsupported password encoding: {encoding_name}")


def _checksum_password_bytes(master_key: bytes, encoding_name: str) -> bytes:
    if encoding_name == "legacy-8bit":
        return bytes(master_key)
    chars = []
    for byte in master_key:
        signed = byte if byte < 0x80 else byte - 0x100
        chars.append(chr(signed & 0xFFFF))
    return "".join(chars).encode("utf-8")


def _make_key_checksum(master_key: bytes, checksum_salt: bytes, rounds: int, encoding_name: str) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha1",
        _checksum_password_bytes(master_key, encoding_name),
        checksum_salt,
        rounds,
        dklen=PBKDF2_KEY_BYTES,
    )


def _parse_master_key_blob(plain: bytes, user_key_encoding: str, header: AndroidBackupHeader) -> MasterKey:
    offset = 0

    def read_length_prefixed(field_name: str) -> bytes:
        nonlocal offset
        if offset >= len(plain):
            raise AndroidBackupDecodeError("malformed master-key structure", f"Missing {field_name} length")
        length = plain[offset]
        offset += 1
        if length <= 0 or offset + length > len(plain):
            raise AndroidBackupDecodeError("malformed master-key structure", f"Invalid {field_name} length")
        value = plain[offset : offset + length]
        offset += length
        return value

    master_iv = read_length_prefixed("master-key IV")
    master_key = read_length_prefixed("master key")
    checksum = read_length_prefixed("master-key checksum")

    if offset != len(plain):
        raise AndroidBackupDecodeError("malformed master-key structure", "Trailing bytes in master-key blob")
    if len(master_iv) != AES_BLOCK_BYTES:
        raise AndroidBackupDecodeError("malformed master-key structure", "Invalid master-key IV length")
    if len(master_key) != PBKDF2_KEY_BYTES:
        raise AndroidBackupDecodeError("malformed master-key structure", "Invalid master key length")
    if len(checksum) != PBKDF2_KEY_BYTES:
        raise AndroidBackupDecodeError("malformed master-key structure", "Invalid master-key checksum length")

    for checksum_encoding in _encoding_order(header.version):
        calculated = _make_key_checksum(master_key, header.checksum_salt, header.rounds, checksum_encoding)
        if hmac.compare_digest(calculated, checksum):
            return MasterKey(
                iv=master_iv,
                key=master_key,
                user_key_encoding=user_key_encoding,
                checksum_encoding=checksum_encoding,
            )

    raise AndroidBackupDecodeError("master-key checksum mismatch", UNAVAILABLE_CREDENTIAL_MESSAGE)


def _unwrap_master_key(header: AndroidBackupHeader, password: str) -> MasterKey:
    failures: list[str] = []
    seen_user_keys: set[bytes] = set()
    for user_key_encoding in _encoding_order(header.version):
        user_key = hashlib.pbkdf2_hmac(
            "sha1",
            _password_bytes(password, user_key_encoding),
            header.user_salt,
            header.rounds,
            dklen=PBKDF2_KEY_BYTES,
        )
        if user_key in seen_user_keys:
            continue
        seen_user_keys.add(user_key)
        try:
            decrypted = AES.new(user_key, AES.MODE_CBC, header.user_iv).decrypt(header.master_key_blob)
            plain = unpad(decrypted, AES_BLOCK_BYTES)
        except ValueError:
            failures.append("master-key padding failure")
            continue

        try:
            return _parse_master_key_blob(plain, user_key_encoding, header)
        except AndroidBackupDecodeError as exc:
            failures.append(exc.phase)

    phase = "master-key padding failure"
    for candidate in (
        "master-key checksum mismatch",
        "malformed master-key structure",
        "master-key padding failure",
    ):
        if candidate in failures:
            phase = candidate
            break
    raise AndroidBackupDecodeError(phase, UNAVAILABLE_CREDENTIAL_MESSAGE)


def _validate_tar_payload(payload: bytes) -> int:
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
            members = archive.getmembers()
    except tarfile.TarError as exc:
        raise AndroidBackupDecodeError("invalid TAR", "Decoded payload is not a valid TAR archive") from exc

    for member in members:
        try:
            safe_relative_parts(member.name)
        except ValueError as exc:
            raise AndroidBackupDecodeError("invalid TAR", "TAR member path is unsafe") from exc
        if not (member.isdir() or member.isfile()):
            raise AndroidBackupDecodeError("invalid TAR", "TAR member type is unsupported")
    return len(members)


def decode_android_backup_file(path: Path, password: str) -> tuple[bytes, dict[str, object]]:
    raw = path.read_bytes()
    header = parse_android_backup_header(raw)
    payload = raw[header.payload_offset :]

    if header.encryption_algorithm == ENCRYPTION_ALGORITHM_AES_256 and len(payload) % AES_BLOCK_BYTES:
        raise AndroidBackupDecodeError("ciphertext not block-aligned", "Payload ciphertext is not AES block aligned")

    meta: dict[str, object] = {
        "version": str(header.version),
        "compressed": int(header.compressed),
        "algorithm": header.encryption_algorithm,
        "payload_len": 0,
    }

    if header.encryption_algorithm == ENCRYPTION_ALGORITHM_NONE:
        plain = payload
    else:
        master_key = _unwrap_master_key(header, password)
        try:
            plain = unpad(AES.new(master_key.key, AES.MODE_CBC, master_key.iv).decrypt(payload), AES_BLOCK_BYTES)
        except ValueError as exc:
            raise AndroidBackupDecodeError("payload padding failure", "Payload padding is invalid") from exc
        meta["user_key_encoding"] = master_key.user_key_encoding
        meta["checksum_encoding"] = master_key.checksum_encoding

    if header.compressed:
        try:
            plain = zlib.decompress(plain)
        except zlib.error as exc:
            raise AndroidBackupDecodeError("zlib decompression failure", "Payload decompression failed") from exc

    meta["tar_entries"] = _validate_tar_payload(plain)
    meta["payload_len"] = len(plain)
    return plain, meta


def inspect_android_backup_file(
    path: Path,
    *,
    credential_candidates: list[str] | None = None,
) -> AndroidBackupInspection:
    raw = path.read_bytes()
    inspection = AndroidBackupInspection(
        file_size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )

    try:
        header = parse_android_backup_header(raw)
    except AndroidBackupDecodeError as exc:
        inspection.phase = exc.phase
        inspection.message = str(exc)
        try:
            magic_raw, _offset = _read_header_line(raw, 0)
            inspection.magic = _decode_ascii(magic_raw, "magic")
        except AndroidBackupDecodeError:
            inspection.magic = ""
        return inspection

    payload = raw[header.payload_offset :]
    inspection.magic = header.magic
    inspection.backup_version = header.version
    inspection.compressed_flag = int(header.compressed)
    inspection.encryption_algorithm = header.encryption_algorithm
    inspection.payload_ciphertext_length = len(payload)
    inspection.payload_aes_aligned = len(payload) % AES_BLOCK_BYTES == 0

    if header.encryption_algorithm == ENCRYPTION_ALGORITHM_AES_256:
        inspection.user_salt_length = len(header.user_salt)
        inspection.checksum_salt_length = len(header.checksum_salt)
        inspection.pbkdf2_rounds = header.rounds
        inspection.user_iv_length = len(header.user_iv)
        inspection.master_key_blob_length = len(header.master_key_blob)
        inspection.master_key_blob_aes_aligned = len(header.master_key_blob) % AES_BLOCK_BYTES == 0
    else:
        try:
            _payload, meta = decode_android_backup_file(path, "")
        except AndroidBackupDecodeError as exc:
            inspection.phase = exc.phase
            inspection.message = str(exc)
            return inspection
        inspection.phase = "ok"
        inspection.message = "Decoded payload is TAR-valid"
        inspection.tar_entries = int(meta.get("tar_entries", 0))
        inspection.details["payload length"] = int(meta.get("payload_len", 0))
        return inspection

    candidates = credential_candidates if credential_candidates is not None else [DEFAULT_DUMMY_HEX]
    if header.encryption_algorithm == ENCRYPTION_ALGORITHM_AES_256 and not candidates:
        inspection.phase = "not attempted"
        inspection.message = "No credential candidate supplied"
        return inspection

    last_error: AndroidBackupDecodeError | None = None
    for password in candidates:
        inspection.credential_attempts += 1
        try:
            _payload, meta = decode_android_backup_file(path, password)
        except AndroidBackupDecodeError as exc:
            last_error = exc
            continue
        inspection.phase = "ok"
        inspection.message = "Decoded payload is authenticated and TAR-valid"
        inspection.tar_entries = int(meta.get("tar_entries", 0))
        inspection.details["payload length"] = int(meta.get("payload_len", 0))
        return inspection

    if last_error is not None:
        inspection.phase = last_error.phase
        inspection.message = str(last_error)
    else:
        inspection.phase = "ok"
        inspection.message = "No encrypted payload to unwrap"
    return inspection

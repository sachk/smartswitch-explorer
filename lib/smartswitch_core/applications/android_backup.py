from __future__ import annotations

import hashlib
import hmac
import tarfile
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import BinaryIO, TypedDict

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from smartswitch_core.archive_safety import (
    ArchiveBudget,
    ArchiveLimitError,
    DiskSpaceGuard,
)
from smartswitch_core.crypto.common import DEFAULT_DUMMY_HEX
from smartswitch_core.path_safety import safe_relative_parts

BACKUP_MAGIC = "ANDROID BACKUP"
SUPPORTED_BACKUP_VERSIONS = range(1, 6)
ENCRYPTION_ALGORITHM_AES_256 = "AES-256"
ENCRYPTION_ALGORITHM_NONE = "none"
PBKDF2_KEY_BYTES = 32
PBKDF2_SALT_BYTES = 64
AES_BLOCK_BYTES = 16
MAX_PBKDF2_ROUNDS = 1_000_000
MAX_HEADER_BYTES = 1024 * 1024
IO_CHUNK_BYTES = 1024 * 1024
DECOMPRESS_CHUNK_BYTES = 4 * 1024 * 1024

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


class AndroidBackupMetadata(TypedDict, total=False):
    version: str
    compressed: int
    algorithm: str
    payload_len: int
    tar_entries: int
    tar_file_bytes: int
    user_key_encoding: str
    checksum_encoding: str
    password_source: str
    extracted_files: int


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
        raise AndroidBackupDecodeError(
            "invalid header", "Missing newline in Android Backup header"
        )
    line = raw[offset:newline]
    if line.endswith(b"\r"):
        line = line[:-1]
    return line, newline + 1


def _decode_ascii(line: bytes, field_name: str) -> str:
    try:
        return line.decode("ascii")
    except UnicodeDecodeError as exc:
        raise AndroidBackupDecodeError(
            "invalid header", f"{field_name} is not ASCII"
        ) from exc


def _parse_int(line: bytes, field_name: str) -> int:
    text = _decode_ascii(line, field_name)
    if not text or not text.isdecimal():
        raise AndroidBackupDecodeError(
            "invalid header", f"{field_name} is not a decimal integer"
        )
    return int(text)


def _parse_hex(line: bytes, field_name: str) -> bytes:
    text = _decode_ascii(line, field_name)
    if len(text) % 2:
        raise AndroidBackupDecodeError(
            "invalid hexadecimal header field", f"{field_name} has odd length"
        )
    if any(ch not in "0123456789abcdefABCDEF" for ch in text):
        raise AndroidBackupDecodeError(
            "invalid hexadecimal header field", f"{field_name} is not hexadecimal"
        )
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
        raise AndroidBackupDecodeError(
            "unsupported format", f"Unsupported Android Backup version: {version}"
        )

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
        raise AndroidBackupDecodeError(
            "unsupported format", f"Unsupported encryption algorithm: {algorithm}"
        )

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
    if rounds <= 0 or rounds > MAX_PBKDF2_ROUNDS:
        raise AndroidBackupDecodeError(
            "invalid field length",
            f"PBKDF2 rounds must be between 1 and {MAX_PBKDF2_ROUNDS:,}",
        )
    if len(user_iv) != AES_BLOCK_BYTES:
        raise AndroidBackupDecodeError(
            "invalid field length", "Invalid user key IV length"
        )
    if not master_key_blob or len(master_key_blob) % AES_BLOCK_BYTES:
        raise AndroidBackupDecodeError(
            "ciphertext not block-aligned", "Master-key blob is not AES block aligned"
        )

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


def _make_key_checksum(
    master_key: bytes, checksum_salt: bytes, rounds: int, encoding_name: str
) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha1",
        _checksum_password_bytes(master_key, encoding_name),
        checksum_salt,
        rounds,
        dklen=PBKDF2_KEY_BYTES,
    )


def _parse_master_key_blob(
    plain: bytes, user_key_encoding: str, header: AndroidBackupHeader
) -> MasterKey:
    offset = 0

    def read_length_prefixed(field_name: str) -> bytes:
        nonlocal offset
        if offset >= len(plain):
            raise AndroidBackupDecodeError(
                "malformed master-key structure", f"Missing {field_name} length"
            )
        length = plain[offset]
        offset += 1
        if length <= 0 or offset + length > len(plain):
            raise AndroidBackupDecodeError(
                "malformed master-key structure", f"Invalid {field_name} length"
            )
        value = plain[offset : offset + length]
        offset += length
        return value

    master_iv = read_length_prefixed("master-key IV")
    master_key = read_length_prefixed("master key")
    checksum = read_length_prefixed("master-key checksum")

    if offset != len(plain):
        raise AndroidBackupDecodeError(
            "malformed master-key structure", "Trailing bytes in master-key blob"
        )
    if len(master_iv) != AES_BLOCK_BYTES:
        raise AndroidBackupDecodeError(
            "malformed master-key structure", "Invalid master-key IV length"
        )
    if len(master_key) != PBKDF2_KEY_BYTES:
        raise AndroidBackupDecodeError(
            "malformed master-key structure", "Invalid master key length"
        )
    if len(checksum) != PBKDF2_KEY_BYTES:
        raise AndroidBackupDecodeError(
            "malformed master-key structure", "Invalid master-key checksum length"
        )

    for checksum_encoding in _encoding_order(header.version):
        calculated = _make_key_checksum(
            master_key, header.checksum_salt, header.rounds, checksum_encoding
        )
        if hmac.compare_digest(calculated, checksum):
            return MasterKey(
                iv=master_iv,
                key=master_key,
                user_key_encoding=user_key_encoding,
                checksum_encoding=checksum_encoding,
            )

    raise AndroidBackupDecodeError(
        "master-key checksum mismatch", UNAVAILABLE_CREDENTIAL_MESSAGE
    )


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
            decrypted = AES.new(user_key, AES.MODE_CBC, header.user_iv).decrypt(
                header.master_key_blob
            )
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


def _read_header_prefix(path: Path) -> bytes:
    with path.open("rb") as source:
        return source.read(MAX_HEADER_BYTES)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(IO_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_plain_chunks(source: BinaryIO) -> Iterator[bytes]:
    while chunk := source.read(IO_CHUNK_BYTES):
        yield chunk


def _iter_decrypted_chunks(
    source: BinaryIO,
    master_key: MasterKey,
) -> Iterator[bytes]:
    cipher = AES.new(master_key.key, AES.MODE_CBC, master_key.iv)
    final_block = b""
    while chunk := source.read(IO_CHUNK_BYTES):
        decrypted = cipher.decrypt(chunk)
        buffered = final_block + decrypted
        if len(buffered) > AES_BLOCK_BYTES:
            yield buffered[:-AES_BLOCK_BYTES]
            final_block = buffered[-AES_BLOCK_BYTES:]
        else:
            final_block = buffered
    try:
        unpadded = unpad(final_block, AES_BLOCK_BYTES)
    except ValueError as exc:
        raise AndroidBackupDecodeError(
            "payload padding failure", "Payload padding is invalid"
        ) from exc
    if unpadded:
        yield unpadded


def _write_checked(
    destination: BinaryIO,
    chunk: bytes,
    disk_guard: DiskSpaceGuard,
) -> int:
    if not chunk:
        return 0
    try:
        disk_guard.consume(len(chunk))
        written = destination.write(chunk)
        if written != len(chunk):
            raise OSError(f"Short write: expected {len(chunk)} bytes, wrote {written}")
    except (ArchiveLimitError, OSError) as exc:
        raise AndroidBackupDecodeError(
            "output write failure", f"Unable to write decoded payload: {exc}"
        ) from exc
    return len(chunk)


def _stream_payload_to_tar(
    chunks: Iterator[bytes],
    destination: BinaryIO,
    *,
    compressed: bool,
    disk_guard: DiskSpaceGuard,
) -> int:
    written = 0
    if not compressed:
        for chunk in chunks:
            written += _write_checked(destination, chunk, disk_guard)
        return written

    decompressor = zlib.decompressobj()
    try:
        for chunk in chunks:
            pending = chunk
            while pending:
                decoded = decompressor.decompress(pending, DECOMPRESS_CHUNK_BYTES)
                pending = decompressor.unconsumed_tail
                written += _write_checked(destination, decoded, disk_guard)
        written += _write_checked(destination, decompressor.flush(), disk_guard)
    except zlib.error as exc:
        raise AndroidBackupDecodeError(
            "zlib decompression failure", "Payload decompression failed"
        ) from exc
    if not decompressor.eof or decompressor.unused_data:
        raise AndroidBackupDecodeError(
            "zlib decompression failure", "Payload decompression failed"
        )
    return written


def _validate_tar_file(path: Path) -> tuple[int, int]:
    budget = ArchiveBudget()
    try:
        with tarfile.open(path, mode="r:") as archive:
            for member in archive:
                try:
                    safe_relative_parts(member.name)
                except ValueError as exc:
                    raise AndroidBackupDecodeError(
                        "invalid TAR", "TAR member path is unsafe"
                    ) from exc
                if not (member.isdir() or member.isfile()):
                    raise AndroidBackupDecodeError(
                        "invalid TAR", "TAR member type is unsupported"
                    )
                try:
                    budget.add(member.size if member.isfile() else 0)
                except ArchiveLimitError as exc:
                    raise AndroidBackupDecodeError(
                        "resource limit exceeded", str(exc)
                    ) from exc
    except tarfile.TarError as exc:
        raise AndroidBackupDecodeError(
            "invalid TAR", "Decoded payload is not a valid TAR archive"
        ) from exc
    return budget.members, budget.bytes


def decode_android_backup_to_tar(
    path: Path,
    password: str,
    output_path: Path,
) -> AndroidBackupMetadata:
    if output_path.exists():
        raise FileExistsError(f"Decoded output already exists: {output_path}")

    file_size = path.stat().st_size
    header = parse_android_backup_header(_read_header_prefix(path))
    payload_size = file_size - header.payload_offset
    if (
        header.encryption_algorithm == ENCRYPTION_ALGORITHM_AES_256
        and payload_size % AES_BLOCK_BYTES
    ):
        raise AndroidBackupDecodeError(
            "ciphertext not block-aligned",
            "Payload ciphertext is not AES block aligned",
        )

    meta: AndroidBackupMetadata = {
        "version": str(header.version),
        "compressed": int(header.compressed),
        "algorithm": header.encryption_algorithm,
        "payload_len": 0,
    }
    master_key: MasterKey | None = None
    if header.encryption_algorithm == ENCRYPTION_ALGORITHM_AES_256:
        master_key = _unwrap_master_key(header, password)
        meta["user_key_encoding"] = master_key.user_key_encoding
        meta["checksum_encoding"] = master_key.checksum_encoding

    output_path.parent.mkdir(parents=True, exist_ok=True)
    complete = False
    try:
        disk_guard = DiskSpaceGuard(output_path.parent)
        with path.open("rb") as source, output_path.open("xb") as destination:
            source.seek(header.payload_offset)
            chunks = (
                _iter_decrypted_chunks(source, master_key)
                if master_key is not None
                else _iter_plain_chunks(source)
            )
            payload_len = _stream_payload_to_tar(
                chunks,
                destination,
                compressed=header.compressed,
                disk_guard=disk_guard,
            )
        tar_entries, tar_bytes = _validate_tar_file(output_path)
        complete = True
    finally:
        if not complete:
            output_path.unlink(missing_ok=True)

    meta["tar_entries"] = tar_entries
    meta["tar_file_bytes"] = tar_bytes
    meta["payload_len"] = payload_len
    return meta


def inspect_android_backup_file(
    path: Path,
    *,
    credential_candidates: list[str] | None = None,
) -> AndroidBackupInspection:
    file_size = path.stat().st_size
    prefix = _read_header_prefix(path)
    inspection = AndroidBackupInspection(
        file_size=file_size,
        sha256=_sha256_file(path),
    )

    try:
        header = parse_android_backup_header(prefix)
    except AndroidBackupDecodeError as exc:
        inspection.phase = exc.phase
        inspection.message = str(exc)
        try:
            magic_raw, _ = _read_header_line(prefix, 0)
            inspection.magic = _decode_ascii(magic_raw, "magic")
        except AndroidBackupDecodeError:
            inspection.magic = ""
        return inspection

    payload_size = file_size - header.payload_offset
    inspection.magic = header.magic
    inspection.backup_version = header.version
    inspection.compressed_flag = int(header.compressed)
    inspection.encryption_algorithm = header.encryption_algorithm
    inspection.payload_ciphertext_length = payload_size
    inspection.payload_aes_aligned = payload_size % AES_BLOCK_BYTES == 0

    if header.encryption_algorithm == ENCRYPTION_ALGORITHM_AES_256:
        inspection.user_salt_length = len(header.user_salt)
        inspection.checksum_salt_length = len(header.checksum_salt)
        inspection.pbkdf2_rounds = header.rounds
        inspection.user_iv_length = len(header.user_iv)
        inspection.master_key_blob_length = len(header.master_key_blob)
        inspection.master_key_blob_aes_aligned = (
            len(header.master_key_blob) % AES_BLOCK_BYTES == 0
        )

    candidates = (
        credential_candidates
        if credential_candidates is not None
        else [DEFAULT_DUMMY_HEX]
    )
    if header.encryption_algorithm == ENCRYPTION_ALGORITHM_NONE:
        candidates = [""]
    elif not candidates:
        inspection.phase = "not attempted"
        inspection.message = "No credential candidate supplied"
        return inspection

    last_error: AndroidBackupDecodeError | None = None
    with TemporaryDirectory(prefix="smartswitch-inspect-") as temporary_directory:
        output_path = Path(temporary_directory) / "decoded.tar"
        for password in candidates:
            inspection.credential_attempts += 1
            try:
                meta = decode_android_backup_to_tar(path, password, output_path)
            except AndroidBackupDecodeError as exc:
                last_error = exc
                continue
            inspection.phase = "ok"
            inspection.message = (
                "Decoded payload is TAR-valid"
                if header.encryption_algorithm == ENCRYPTION_ALGORITHM_NONE
                else "Decoded payload is authenticated and TAR-valid"
            )
            inspection.tar_entries = int(meta.get("tar_entries", 0))
            inspection.details["payload length"] = int(meta.get("payload_len", 0))
            return inspection

    if last_error is not None:
        inspection.phase = last_error.phase
        inspection.message = str(last_error)
    return inspection

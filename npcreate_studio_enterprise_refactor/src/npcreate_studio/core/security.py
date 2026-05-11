from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from .errors import SecurityError

DEFAULT_MAX_ARCHIVE_BYTES = 80 * 1024 * 1024
DEFAULT_MAX_EXTRACTED_BYTES = 350 * 1024 * 1024
DEFAULT_MAX_FILES = 5000


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def generate_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def encode_secret(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def decode_secret(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))


def safe_join(root: Path, *parts: str | Path) -> Path:
    root = root.resolve()
    candidate = root.joinpath(*map(str, parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SecurityError(f"path escapes allowed root: {candidate}") from exc
    return candidate


def _is_windows_abs_or_drive(name: str) -> bool:
    win = PureWindowsPath(name)
    return bool(win.drive or win.root)


def is_safe_archive_member(name: str) -> bool:
    if not name or name.startswith("/") or name.startswith("\\"):
        return False
    if _is_windows_abs_or_drive(name):
        return False
    posix = PurePosixPath(name)
    if posix.is_absolute():
        return False
    if any(part in ("", ".", "..") for part in posix.parts):
        return False
    if "\x00" in name:
        return False
    return True


def _zipinfo_is_link(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode in (stat.S_IFLNK, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO, stat.S_IFSOCK)


@dataclass(frozen=True)
class ExtractReport:
    files: int
    compressed_bytes: int
    extracted_bytes: int
    destination: Path


def safe_extract_zip(
    archive: Path,
    destination: Path,
    *,
    max_archive_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    max_extracted_bytes: int = DEFAULT_MAX_EXTRACTED_BYTES,
    max_files: int = DEFAULT_MAX_FILES,
    strip_first_dir: bool = False,
) -> ExtractReport:
    """Extract ZIP safely.

    Blocks path traversal, absolute paths, Windows drive paths, special files,
    excessive file counts and basic zip-bomb patterns. Do not use ZipFile.extractall().
    """
    archive = archive.resolve()
    destination = destination.resolve()
    if archive.stat().st_size > max_archive_bytes:
        raise SecurityError(f"archive too large: {archive.stat().st_size}")

    destination.mkdir(parents=True, exist_ok=True)
    total_uncompressed = 0
    total_compressed = 0
    files = 0

    with zipfile.ZipFile(archive) as zf:
        infos = [info for info in zf.infolist() if not info.is_dir()]
        if len(infos) > max_files:
            raise SecurityError(f"too many files in archive: {len(infos)}")
        prefix = _common_zip_prefix([i.filename for i in infos]) if strip_first_dir else ""
        for info in infos:
            if _zipinfo_is_link(info):
                raise SecurityError(f"archive contains unsupported link/special file: {info.filename}")
            name = info.filename[len(prefix):] if prefix and info.filename.startswith(prefix) else info.filename
            if not is_safe_archive_member(name):
                raise SecurityError(f"unsafe archive path: {info.filename}")
            total_uncompressed += int(info.file_size)
            total_compressed += int(info.compress_size)
            if total_uncompressed > max_extracted_bytes:
                raise SecurityError("archive extracted size exceeds limit")
            target = safe_join(destination, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            files += 1

    return ExtractReport(files, total_compressed, total_uncompressed, destination)


def _common_zip_prefix(names: list[str]) -> str:
    if not names:
        return ""
    first = names[0]
    if "/" not in first:
        return ""
    prefix = first.split("/", 1)[0] + "/"
    if prefix.startswith("__MACOSX"):
        return ""
    return prefix if all(n.startswith(prefix) for n in names) else ""


def secure_random_filename(prefix: str, suffix: str) -> str:
    safe_prefix = "".join(c for c in prefix if c.isalnum() or c in "-_")[:40] or "file"
    return f"{safe_prefix}-{secrets.token_hex(8)}{suffix}"


def ensure_private_file(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o600)

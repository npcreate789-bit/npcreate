"""Customer-portable state backup/restore.

What it solves
--------------

When the customer reformats their PC, buys a new laptop, or asks a
friend to set them up on a second machine, they currently re-pair
every phone and re-import every device profile by hand. This module
bundles all the portable state into a single ZIP that drops onto a
USB stick and restores on the new machine with one click.

What we save
------------

Files under ``settings.app_data_path`` named in ``INCLUDE`` —
currently the device-profile library and the client-state cache.
The activation tokens are NOT included on purpose: they're encrypted
with a machine-bound key (``SecureStore``) and would be useless on
another machine even if we did ship them. The customer re-enters the
license key once when prompted.

What we never save (defence in depth)
-------------------------------------

Anything matching a ``FORBIDDEN_FILENAMES`` entry at *any* depth in
the archive is dropped, both when creating and when restoring. The
list covers signing seeds (``.private_key``), token blobs, and any
other secret that could be smuggled into a hand-crafted backup ZIP
aimed at the customer.

Atomicity on restore
--------------------

Extract to a temp staging dir → validate the schema → ``os.replace``
each file into ``app_data_path``. A botched ZIP (truncated, wrong
schema, path traversal) never mutates the live install: the only
mutable state up to the replace step is inside the staging dir,
which is unconditionally torn down on exit.
"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
import time
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from ..core.security import is_safe_archive_member, safe_join

log = logging.getLogger(__name__)

SCHEMA_VERSION = 2


@dataclass(frozen=True)
class BackupManifest:
    """Embedded in every backup ZIP as ``manifest.json``. The schema
    field gates compatibility on restore: the service refuses anything
    it doesn't explicitly understand to avoid silently doing the wrong
    thing on a future incompatible bump."""

    schema: int
    app_name: str
    app_version: str
    created_at: str
    files: list[str]


@dataclass(frozen=True)
class BackupResult:
    path: Path
    files: list[str]
    manifest: BackupManifest


class BackupService:
    """Bundle the customer's portable state under ``app_data_dir`` into a
    single ZIP, and put it back on demand.

    ``app_name`` + ``app_version`` are embedded in the manifest for
    diagnostics — a customer support session can ask "which version did
    you back up from?" without poking at filenames.
    """

    INCLUDE: tuple[str, ...] = (
        "device_profiles.json",
        "client_state.json",
    )

    FORBIDDEN_FILENAMES: frozenset[str] = frozenset({
        ".private_key",
        "master.key",
        "tokens",
        "tokens.bin",
        "tokens.sqlite3",
        "secure_store.bin",
    })

    def __init__(
        self,
        app_data_dir: Path,
        *,
        app_name: str = "NP Create Studio",
        app_version: str = "0.0.0",
    ) -> None:
        self.app_data_dir = app_data_dir.resolve()
        self.app_name = app_name
        self.app_version = app_version

    # ── create ────────────────────────────────────────────────────────

    def create_backup(self, out_path: Path) -> BackupResult:
        out_path = Path(out_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        added: list[str] = []
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for rel in self.INCLUDE:
                if Path(rel).name in self.FORBIDDEN_FILENAMES:
                    # Belt and suspenders: future devs editing INCLUDE
                    # can't accidentally leak a secret.
                    continue
                src = self.app_data_dir / rel
                if not src.is_file():
                    continue
                zf.write(src, arcname=rel)
                added.append(rel)

            created_at = datetime.now().isoformat(timespec="seconds")
            manifest = BackupManifest(
                schema=SCHEMA_VERSION,
                app_name=self.app_name,
                app_version=self.app_version,
                created_at=created_at,
                files=added,
            )
            zf.writestr(
                "manifest.json",
                json.dumps(asdict(manifest), indent=2, ensure_ascii=False),
            )
            zf.writestr(
                "README.txt",
                self._readme_text(manifest),
            )

        return BackupResult(path=out_path, files=added, manifest=manifest)

    def _readme_text(self, manifest: BackupManifest) -> str:
        return (
            f"{manifest.app_name} v{manifest.app_version} backup\n"
            f"Created: {manifest.created_at}\n"
            f"\n"
            f"Restore on the destination machine:\n"
            f"  1. Open {manifest.app_name}.\n"
            f"  2. Settings → Backup / Restore → 'Restore from ZIP'.\n"
            f"  3. Pick this file.\n"
            f"\n"
            f"This backup contains the customer's local state only. The\n"
            f"license key is bound to the activation machine and resumes\n"
            f"automatically there; on a different machine, re-enter it\n"
            f"once when prompted.\n"
        )

    # ── peek ─────────────────────────────────────────────────────────

    def list_files(self, zip_path: Path) -> list[str]:
        """Return every member of the ZIP, including the manifest and
        README. UI uses this to render a "this backup has N files"
        preview before the user commits to restoring."""
        zip_path = Path(zip_path)
        if not zip_path.is_file():
            return []
        try:
            with zipfile.ZipFile(zip_path) as zf:
                return zf.namelist()
        except zipfile.BadZipFile:
            return []

    def read_manifest(self, zip_path: Path) -> BackupManifest | None:
        """Parse ``manifest.json`` out of the ZIP. Returns ``None`` on
        anything malformed — the UI uses that to refuse a restore from
        a non-NPCreate ZIP (customer picked the wrong file)."""
        zip_path = Path(zip_path)
        try:
            with zipfile.ZipFile(zip_path) as zf:
                with zf.open("manifest.json") as f:
                    payload = json.loads(f.read().decode("utf-8"))
        except (KeyError, zipfile.BadZipFile, json.JSONDecodeError, OSError):
            return None
        if not isinstance(payload, dict):
            return None
        try:
            return BackupManifest(
                schema=int(payload.get("schema", 1)),
                app_name=str(payload.get("app_name", "")),
                app_version=str(payload.get("app_version", "")),
                created_at=str(payload.get("created_at", "")),
                files=[str(x) for x in payload.get("files", [])],
            )
        except (TypeError, ValueError):
            return None

    # ── restore ──────────────────────────────────────────────────────

    def restore_backup(self, zip_path: Path) -> list[str]:
        """Atomically restore the named ZIP into ``app_data_dir``.

        Order: peek manifest → schema gate → extract to ``tempfile``
        staging → second pass moves into place. The staging dir is
        always removed on exit, including when an exception is raised.
        """
        zip_path = Path(zip_path).resolve()
        manifest = self.read_manifest(zip_path)
        if manifest is None:
            raise ValueError("ไฟล์ไม่ใช่ Backup ของ NP Create (manifest หายหรือเสีย)")
        if manifest.schema != SCHEMA_VERSION:
            raise ValueError(
                f"Backup สร้างจาก schema v{manifest.schema} "
                f"ระบบรู้จักเฉพาะ v{SCHEMA_VERSION}",
            )

        restored: list[str] = []
        with tempfile.TemporaryDirectory(prefix="npcreate-restore-") as td:
            staging = Path(td)
            with zipfile.ZipFile(zip_path) as zf:
                for member in zf.namelist():
                    if member in ("manifest.json", "README.txt") or member.endswith("/"):
                        continue
                    if not is_safe_archive_member(member):
                        log.warning("skipping unsafe entry in backup: %s", member)
                        continue
                    # Defence in depth: reject forbidden filenames at any
                    # depth — a hand-crafted ZIP must not smuggle a
                    # private key into the install.
                    if any(p in self.FORBIDDEN_FILENAMES for p in Path(member).parts):
                        log.warning("forbidden filename in backup: %s", member)
                        continue
                    staged = safe_join(staging, member)
                    staged.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, staged.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    restored.append(member)

            # Second pass: move into place. Fall back to copy+unlink when
            # ``os.replace`` can't cross filesystems (TMPDIR vs
            # app_data_dir on different mounts).
            for member in restored:
                staged = safe_join(staging, member)
                dest = safe_join(self.app_data_dir, member)
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    staged.replace(dest)
                except OSError:
                    shutil.copy2(staged, dest)
                    staged.unlink(missing_ok=True)

        log.info("restored %d files from %s into %s", len(restored), zip_path, self.app_data_dir)
        return restored

    # ── filename helper ──────────────────────────────────────────────

    def suggest_filename(self, *, now: int | None = None) -> str:
        """``npcreate-backup-v2.4.0-20260511-2330.zip``."""
        ts_source = time.localtime(now) if now is not None else time.localtime()
        ts = time.strftime("%Y%m%d-%H%M", ts_source)
        safe_version = "".join(c if c.isalnum() or c in "._-" else "-" for c in self.app_version)
        return f"npcreate-backup-v{safe_version}-{ts}.zip"


__all__ = [
    "SCHEMA_VERSION",
    "BackupManifest",
    "BackupResult",
    "BackupService",
]

from __future__ import annotations

import json
import shutil
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ..core.security import is_safe_archive_member, safe_join


@dataclass(frozen=True)
class BackupResult:
    path: Path
    files: list[str]


class BackupService:
    INCLUDE = ("config.json", "device_profiles.json", "customer_devices.json", "license_history.json")
    EXCLUDE_NAMES = {".private_key", "master.key", "tokens.sqlite3"}

    def __init__(self, project_root: Path, app_data_dir: Path) -> None:
        self.project_root = project_root.resolve()
        self.app_data_dir = app_data_dir.resolve()

    def create_backup(self, out_path: Path) -> BackupResult:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        added: list[str] = []
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for rel in self.INCLUDE:
                src = self.project_root / rel
                if src.is_file() and src.name not in self.EXCLUDE_NAMES:
                    zf.write(src, rel)
                    added.append(rel)
            manifest = {"schema": 2, "created_at": int(time.time()), "files": added}
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return BackupResult(out_path, added)

    def restore_backup(self, zip_path: Path) -> list[str]:
        restored: list[str] = []
        staging = self.app_data_dir / "restore_staging"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        try:
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                if "manifest.json" not in names:
                    raise ValueError("backup manifest missing")
                for name in names:
                    if name == "manifest.json" or name.endswith("/"):
                        continue
                    if not is_safe_archive_member(name):
                        raise ValueError(f"unsafe backup entry: {name}")
                    if Path(name).name in self.EXCLUDE_NAMES:
                        continue
                    target = safe_join(staging, name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(name) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    restored.append(name)
            for rel in restored:
                src = safe_join(staging, rel)
                dest = safe_join(self.project_root, rel)
                dest.parent.mkdir(parents=True, exist_ok=True)
                src.replace(dest)
            return restored
        finally:
            shutil.rmtree(staging, ignore_errors=True)

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.errors import ToolVerificationError
from ..core.security import sha256_file

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolFile:
    logical_name: str
    relative_path: str
    sha256: str
    size: int | None = None
    required: bool = True


@dataclass(frozen=True)
class ToolVerificationReport:
    ok: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.missing and not self.invalid


class ToolchainResolver:
    def __init__(self, *, root: Path, manifest_path: Path) -> None:
        self.root = root.resolve()
        self.manifest_path = manifest_path.resolve()
        self._manifest: list[ToolFile] | None = None

    def load_manifest(self) -> list[ToolFile]:
        if self._manifest is not None:
            return self._manifest
        if not self.manifest_path.is_file():
            self._manifest = []
            return self._manifest
        raw: dict[str, Any] = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        files = []
        for item in raw.get("files", []):
            files.append(
                ToolFile(
                    logical_name=str(item["logical_name"]),
                    relative_path=str(item["relative_path"]),
                    sha256=str(item["sha256"]),
                    size=int(item["size"]) if item.get("size") is not None else None,
                    required=bool(item.get("required", True)),
                )
            )
        self._manifest = files
        return files

    def resolve(self, logical_name: str, *, verify: bool = True) -> Path:
        for item in self.load_manifest():
            if item.logical_name == logical_name:
                path = (self.root / item.relative_path).resolve()
                try:
                    path.relative_to(self.root)
                except ValueError as exc:
                    raise ToolVerificationError(f"tool path escapes root: {item.relative_path}") from exc
                if verify:
                    self.verify_one(item)
                return path
        raise FileNotFoundError(f"tool not in manifest: {logical_name}")

    def resolve_or_path(self, logical_name: str, *, path_name: str | None = None) -> Path | None:
        """Manifest-first resolution with a system-PATH fallback.

        Production builds carry a signed manifest and want manifest-only
        resolution (use :meth:`resolve`). Dev boxes with Homebrew / apt-get
        installs benefit from PATH fallback so the GUI is usable without
        someone pre-populating ``vendor/``. Returns ``None`` when neither
        lookup succeeds — callers decide whether that's a toast or a hard
        error.
        """
        try:
            return self.resolve(logical_name)
        except FileNotFoundError:
            pass
        found = shutil.which(path_name or logical_name)
        return Path(found) if found else None

    def verify_one(self, item: ToolFile) -> None:
        path = (self.root / item.relative_path).resolve()
        if not path.is_file():
            raise ToolVerificationError(f"missing tool: {item.logical_name}")
        if item.size is not None and path.stat().st_size != item.size:
            raise ToolVerificationError(f"size mismatch: {item.logical_name}")
        actual = sha256_file(path)
        if actual.lower() != item.sha256.lower():
            raise ToolVerificationError(f"sha256 mismatch: {item.logical_name}")

    def verify_all(self, *, required: bool = True) -> ToolVerificationReport:
        ok: list[str] = []
        missing: list[str] = []
        invalid: list[str] = []
        for item in self.load_manifest():
            if required and not item.required:
                continue
            try:
                self.verify_one(item)
                ok.append(item.logical_name)
            except FileNotFoundError:
                missing.append(item.logical_name)
            except ToolVerificationError as exc:
                msg = f"{item.logical_name}: {exc}"
                if "missing" in str(exc):
                    missing.append(msg)
                else:
                    invalid.append(msg)
        return ToolVerificationReport(ok=ok, missing=missing, invalid=invalid)

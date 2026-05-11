from __future__ import annotations

import shutil
from pathlib import Path

from ..core.security import safe_join


def atomic_replace_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    shutil.copy2(src, tmp)
    tmp.replace(dest)


def ensure_inside(root: Path, path: Path) -> Path:
    return safe_join(root, path)

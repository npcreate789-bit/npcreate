from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from npcreate_studio.core.security import sha256_file

DEFAULT_TOOL_NAMES = {
    "adb.exe": "adb",
    "adb": "adb",
    "fastboot.exe": "fastboot",
    "ffmpeg.exe": "ffmpeg",
    "ffprobe.exe": "ffprobe",
    "scrcpy.exe": "scrcpy",
    "mediamtx.exe": "mediamtx",
    "java.exe": "java",
    "lspatch.jar": "lspatch",
    "vcam-app-release.apk": "vcam_apk",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate tools_manifest.json from vendor directory")
    parser.add_argument("--root", default="vendor/windows")
    parser.add_argument("--out", default="tools_manifest.json")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        logical = DEFAULT_TOOL_NAMES.get(path.name)
        if logical is None:
            continue
        files.append({
            "logical_name": logical,
            "relative_path": path.relative_to(root).as_posix(),
            "sha256": sha256_file(path),
            "size": path.stat().st_size,
            "required": True,
        })
    payload = {
        "schema": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "root": args.root,
        "files": files,
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.out} with {len(files)} tools")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

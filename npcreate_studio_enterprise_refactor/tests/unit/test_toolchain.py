import json
from pathlib import Path

from npcreate_studio.core.security import sha256_file
from npcreate_studio.infrastructure.toolchain import ToolchainResolver


def test_toolchain_verifies_hash(tmp_path: Path) -> None:
    root = tmp_path / "vendor"
    root.mkdir()
    tool = root / "adb.exe"
    tool.write_text("fake", encoding="utf-8")
    manifest = tmp_path / "tools_manifest.json"
    manifest.write_text(json.dumps({
        "schema": 1,
        "files": [{
            "logical_name": "adb",
            "relative_path": "adb.exe",
            "sha256": sha256_file(tool),
            "size": tool.stat().st_size,
            "required": True,
        }]
    }), encoding="utf-8")
    resolver = ToolchainResolver(root=root, manifest_path=manifest)
    assert resolver.resolve("adb").name == "adb.exe"
    assert resolver.verify_all().passed

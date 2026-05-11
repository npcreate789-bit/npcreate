from __future__ import annotations

import argparse
from pathlib import Path

from npcreate_studio.infrastructure.toolchain import ToolchainResolver


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify bundled tool SHA256 manifest")
    parser.add_argument("--root", default="vendor/windows")
    parser.add_argument("--manifest", default="tools_manifest.json")
    args = parser.parse_args(argv)

    resolver = ToolchainResolver(root=Path(args.root), manifest_path=Path(args.manifest))
    report = resolver.verify_all(required=False)
    for name in report.ok:
        print(f"OK      {name}")
    for name in report.missing:
        print(f"MISSING {name}")
    for name in report.invalid:
        print(f"INVALID {name}")
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

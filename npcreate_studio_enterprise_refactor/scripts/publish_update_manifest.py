"""Publish a signed update manifest via direct DB access.

Server-side maintenance script. The update is signed with the backend's
ed25519 private key from BackendSettings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
from pathlib import Path

from npcreate_backend.billing import audit_log
from npcreate_backend.db import connect, migrate
from npcreate_backend.security import iso, sign_update_manifest, utcnow
from npcreate_backend.settings import BackendSettings


def main() -> None:
    ap = argparse.ArgumentParser(description="Publish a signed update manifest via direct DB access")
    ap.add_argument("--version", required=True)
    ap.add_argument("--download-url", required=True)
    ap.add_argument("--file", required=True, help="Patch file used to calculate sha256")
    ap.add_argument("--channel", default="stable", choices=["stable", "beta", "dev"])
    ap.add_argument("--mandatory", action="store_true")
    ap.add_argument("--release-notes", default="")
    ap.add_argument("--actor", default="cli")
    ap.add_argument("--database-url", default="")
    ap.add_argument("--database-path", default="")
    args = ap.parse_args()

    settings = BackendSettings()
    if not settings.ed25519_private_key_hex:
        raise SystemExit("NPCREATE_BACKEND_ED25519_PRIVATE_KEY_HEX is required to sign updates")

    sha256 = hashlib.sha256(Path(args.file).read_bytes()).hexdigest()
    signature = sign_update_manifest(
        settings.ed25519_private_key_hex,
        version=args.version,
        channel=args.channel,
        mandatory=args.mandatory,
        download_url=args.download_url,
        sha256=sha256,
    )

    target = args.database_url or args.database_path or settings.db_target
    conn = connect(target)
    migrate(conn)
    update_id = "upd_" + secrets.token_urlsafe(18)
    conn.execute(
        """
        INSERT INTO update_manifests(update_id, version, channel, mandatory, download_url, sha256, signature, release_notes, is_active, published_at)
        VALUES(?,?,?,?,?,?,?,?,1,?)
        """,
        (update_id, args.version, args.channel, int(args.mandatory), args.download_url, sha256, signature, args.release_notes, iso(utcnow())),
    )
    audit_log(conn, actor_type="cli", actor_id=args.actor, action="update.publish", target_type="update_manifest", target_id=update_id, metadata={"version": args.version, "channel": args.channel, "mandatory": args.mandatory})
    conn.commit()
    print(json.dumps({"update_id": update_id, "version": args.version, "sha256": sha256, "signature": signature}, ensure_ascii=False))


if __name__ == "__main__":
    main()

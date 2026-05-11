from __future__ import annotations

import hashlib
import json
import logging
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ..core.errors import SecurityError
from ..core.security import safe_extract_zip

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class UpdateManifest:
    version: str
    kind: str
    download_url: str
    sha256: str
    signature_hex: str | None = None


class UpdaterService:
    def __init__(self, public_key_hex: str, install_src_dir: Path) -> None:
        self.public_key_hex = public_key_hex
        self.install_src_dir = install_src_dir.resolve()

    def verify_payload(self, payload: bytes, signature_hex: str) -> None:
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(self.public_key_hex))
        try:
            public_key.verify(bytes.fromhex(signature_hex), payload)
        except InvalidSignature as exc:
            raise SecurityError("update manifest signature invalid") from exc

    @staticmethod
    def parse_manifest(raw: bytes) -> UpdateManifest:
        data = json.loads(raw.decode("utf-8"))
        return UpdateManifest(
            version=str(data["version"]),
            kind=str(data.get("kind", "source")),
            download_url=str(data["download_url"]),
            sha256=str(data["sha256"]),
            signature_hex=data.get("signature"),
        )

    def download_and_verify(self, manifest: UpdateManifest, *, max_bytes: int = 80_000_000) -> Path:
        with urllib.request.urlopen(manifest.download_url, timeout=15) as resp:  # noqa: S310
            data = resp.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise SecurityError("update package exceeds size limit")
        digest = hashlib.sha256(data).hexdigest()
        if digest.lower() != manifest.sha256.lower():
            raise SecurityError("update package sha256 mismatch")
        out = Path(tempfile.mkdtemp(prefix="npcreate-update-")) / "update.zip"
        out.write_bytes(data)
        return out

    def stage_source_patch(self, archive: Path) -> Path:
        staging = Path(tempfile.mkdtemp(prefix="npcreate-src-stage-"))
        safe_extract_zip(archive, staging, strip_first_dir=True)
        if not (staging / "npcreate_studio").exists() and not (staging / "main.py").exists():
            raise SecurityError("source patch missing expected package entrypoint")
        return staging

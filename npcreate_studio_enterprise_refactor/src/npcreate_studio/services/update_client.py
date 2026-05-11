from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, Field

from ..core.errors import SecurityError
from ..core.security import safe_extract_zip


class UpdateManifestResponse(BaseModel):
    version: str
    channel: str = "stable"
    mandatory: bool = False
    download_url: str
    sha256: str = Field(min_length=64, max_length=64)
    signature: str
    release_notes: str = ""


@dataclass(frozen=True)
class UpdateClient:
    base_url: str
    app_version: str
    channel: str
    public_key_hex: str
    timeout_seconds: float = 15.0

    def check_latest(self, activation_token: str | None = None) -> UpdateManifestResponse | None:
        headers = {"X-NPCreate-App-Version": self.app_version}
        if activation_token:
            headers["Authorization"] = f"Bearer {activation_token}"
        with httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds) as client:
            r = client.get("/api/v1/updates/latest", params={"channel": self.channel}, headers=headers)
            if r.status_code == 204:
                return None
            r.raise_for_status()
            return UpdateManifestResponse.model_validate(r.json())

    def verify_manifest_signature(self, manifest: UpdateManifestResponse) -> None:
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(self.public_key_hex))
        signed_payload = (
            f"{manifest.version}|{manifest.channel}|{manifest.mandatory}|"
            f"{manifest.download_url}|{manifest.sha256}"
        ).encode("utf-8")
        try:
            public_key.verify(bytes.fromhex(manifest.signature), signed_payload)
        except InvalidSignature as exc:
            raise SecurityError("update manifest signature invalid") from exc

    def download_patch(self, manifest: UpdateManifestResponse, target_file: Path, *, max_bytes: int = 150_000_000) -> Path:
        self.verify_manifest_signature(manifest)
        with httpx.stream("GET", manifest.download_url, timeout=self.timeout_seconds, follow_redirects=False) as resp:
            resp.raise_for_status()
            hasher = hashlib.sha256()
            written = 0
            target_file.parent.mkdir(parents=True, exist_ok=True)
            with target_file.open("wb") as f:
                for chunk in resp.iter_bytes(1024 * 1024):
                    written += len(chunk)
                    if written > max_bytes:
                        raise SecurityError("update package exceeds max size")
                    hasher.update(chunk)
                    f.write(chunk)
        if hasher.hexdigest().lower() != manifest.sha256.lower():
            target_file.unlink(missing_ok=True)
            raise SecurityError("update package sha256 mismatch")
        return target_file

    def stage_patch_zip(self, patch_zip: Path, staging_dir: Path) -> Path:
        safe_extract_zip(patch_zip, staging_dir, strip_first_dir=True)
        return staging_dir

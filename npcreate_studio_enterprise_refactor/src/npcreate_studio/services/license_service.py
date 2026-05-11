from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ..core.errors import SecurityError
from ..domain.licenses import VerifiedLicense


@dataclass(frozen=True)
class LicenseVerifier:
    public_key_hex: str

    def verify(self, payload_json: str, signature_hex: str) -> VerifiedLicense:
        payload_bytes = payload_json.encode("utf-8")
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(self.public_key_hex))
        try:
            public_key.verify(bytes.fromhex(signature_hex), payload_bytes)
        except InvalidSignature as exc:
            raise SecurityError("license signature invalid") from exc
        payload = json.loads(payload_json)
        expires = payload.get("expires_at")
        expires_at = None
        if expires:
            expires_at = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if expires_at < datetime.now(timezone.utc):
                raise SecurityError("license expired")
        return VerifiedLicense(
            license_id=str(payload["license_id"]),
            customer_name=str(payload.get("customer_name", "")),
            expires_at=expires_at,
            max_devices=int(payload.get("max_devices", 1)),
            features=tuple(payload.get("features", [])),
        )

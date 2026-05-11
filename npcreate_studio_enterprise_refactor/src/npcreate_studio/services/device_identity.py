from __future__ import annotations

import hashlib
import json
import platform
import socket
import uuid
from dataclasses import dataclass
from typing import Mapping

from ..domain.licenses import DeviceIdentity, DeviceType


@dataclass(frozen=True)
class DeviceIdentityService:
    """Create privacy-preserving device fingerprints.

    The backend receives only a SHA-256 fingerprint, not raw serial numbers.
    For Android devices, pass metadata collected by the ADB service, for example:
    serial, ro.product.manufacturer, ro.product.model, ro.serialno, android_id.
    """

    salt: str = "npcreate-studio-v2"

    @staticmethod
    def _canonical_json(data: Mapping[str, object]) -> str:
        return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def _hash(self, data: Mapping[str, object]) -> str:
        payload = {"salt": self.salt, "data": dict(data)}
        return hashlib.sha256(self._canonical_json(payload).encode("utf-8")).hexdigest()

    def pc_identity(self) -> DeviceIdentity:
        metadata: dict[str, object] = {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "node": socket.gethostname(),
            "mac": f"{uuid.getnode():012x}",
        }
        return DeviceIdentity(
            device_type=DeviceType.PC,
            fingerprint_hash=self._hash(metadata),
            label=f"{metadata['node']} / {metadata['system']} {metadata['release']}",
            raw_metadata=metadata,
        )

    def phone_identity(self, adb_metadata: Mapping[str, object]) -> DeviceIdentity:
        required = {"serial", "manufacturer", "model"}
        missing = [k for k in required if not adb_metadata.get(k)]
        if missing:
            raise ValueError(f"missing android identity metadata: {', '.join(missing)}")
        metadata = {k: str(adb_metadata.get(k, "")) for k in sorted(adb_metadata)}
        return DeviceIdentity(
            device_type=DeviceType.PHONE,
            fingerprint_hash=self._hash(metadata),
            label=f"{metadata.get('manufacturer', '')} {metadata.get('model', '')}".strip(),
            raw_metadata=metadata,
        )

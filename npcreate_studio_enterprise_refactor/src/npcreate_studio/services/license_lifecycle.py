"""Orchestrate the activation lifecycle on the client.

Talks to LicenseClient (HTTP) and SecureStore (encrypted disk), so the UI can
just call:

    service.activate("NP-XXXX-...")
    service.heartbeat()
    service.current_state()

State returned to the UI is a plain dict so it can be rendered directly in
CustomTkinter without leaking httpx/secure_store details.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from ..domain.licenses import DeviceIdentity
from ..infrastructure.secure_store import SecureStore
from .device_identity import DeviceIdentityService
from .license_client import LicenseClient

log = logging.getLogger(__name__)

# Refresh proactively if the access token is within this window of expiry.
ACCESS_REFRESH_LEEWAY = timedelta(minutes=2)


@dataclass(frozen=True)
class ActivationStatus:
    license_id: str
    device_id: str
    expires_at: datetime
    features: tuple[str, ...]
    activated: bool = True


class LicenseLifecycleService:
    def __init__(
        self,
        *,
        client: LicenseClient,
        store: SecureStore,
        identity_service: DeviceIdentityService | None = None,
    ) -> None:
        self.client = client
        self.store = store
        self.identity_service = identity_service or DeviceIdentityService()

    # --- public API -------------------------------------------------------

    def activate(self, license_key: str, identity: DeviceIdentity | None = None) -> ActivationStatus:
        """Activate this PC against the backend and persist the resulting tokens."""
        identity = identity or self.identity_service.pc_identity()
        result = self.client.activate(license_key, identity)
        self._persist(result)
        return ActivationStatus(
            license_id=result.license_id,
            device_id=result.device_id,
            expires_at=result.expires_at,
            features=tuple(result.features),
        )

    def current_state(self) -> ActivationStatus | None:
        tokens = self.store.get_tokens()
        if not tokens:
            return None
        expires_at = _parse_dt(tokens.get("license_expires_at"))
        if expires_at is None:
            return None
        return ActivationStatus(
            license_id=str(tokens.get("license_id", "")),
            device_id=str(tokens.get("device_id", "")),
            expires_at=expires_at,
            features=tuple(tokens.get("features", [])),
        )

    def heartbeat(self) -> dict:
        """Heartbeat using stored access token; auto-refresh on 401."""
        tokens = self.store.get_tokens()
        if not tokens:
            raise RuntimeError("no stored activation; call activate() first")
        access = self._access_token_or_refresh(tokens)
        try:
            return self.client.heartbeat(access)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 401:
                raise
            # Retry once with a freshly rotated access token.
            log.info("heartbeat 401 — rotating refresh token and retrying")
            access = self._force_refresh(tokens)
            return self.client.heartbeat(access)

    def clear(self) -> None:
        """Forget local activation (e.g. after admin release)."""
        self.store.clear_tokens()

    # --- internals --------------------------------------------------------

    def _persist(self, result) -> None:
        # ActivationResult is a dataclass from domain.licenses
        self.store.save_tokens({
            "license_id": result.license_id,
            "device_id": result.device_id,
            "access_token": result.activation_token,
            "refresh_token": result.refresh_token,
            "license_expires_at": result.expires_at.isoformat().replace("+00:00", "Z"),
            "features": list(result.features),
            "saved_at": _now_iso(),
        })

    def _access_token_or_refresh(self, tokens: dict) -> str:
        """Return a usable access token; rotate refresh if expiry is near."""
        access = tokens.get("access_token") or ""
        access_expires = _parse_dt(tokens.get("access_expires_at"))
        if access_expires and access_expires - _utcnow() <= ACCESS_REFRESH_LEEWAY:
            return self._force_refresh(tokens)
        return access

    def _force_refresh(self, tokens: dict) -> str:
        refresh = tokens.get("refresh_token") or ""
        if not refresh:
            raise RuntimeError("no refresh token stored")
        rotated = self.client.refresh(refresh)
        new_tokens = dict(tokens)
        new_tokens["access_token"] = rotated.access_token
        new_tokens["refresh_token"] = rotated.refresh_token
        new_tokens["access_expires_at"] = rotated.expires_at.isoformat().replace("+00:00", "Z")
        new_tokens["saved_at"] = _now_iso()
        self.store.save_tokens(new_tokens)
        return rotated.access_token


def _now_iso() -> str:
    return _utcnow().isoformat().replace("+00:00", "Z")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _parse_dt(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None

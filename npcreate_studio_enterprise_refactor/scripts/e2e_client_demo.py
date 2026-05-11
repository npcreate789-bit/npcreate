"""End-to-end client → server smoke flow using the real client services.

Drives the same path a UI would:
  1. Generate a PC device identity (privacy-preserving fingerprint).
  2. Call LicenseClient.activate() → backend issues access + refresh tokens.
  3. Heartbeat using the access token.
  4. Fetch news via the access token.
  5. Refresh the refresh token (rotation) and heartbeat again.
  6. Submit an error report via ErrorReporter (verifies X-API-Key path).

Run with the backend already up on http://127.0.0.1:8088.
"""
from __future__ import annotations

import argparse
import sys

from npcreate_studio.core.settings import Settings
from npcreate_studio.services.device_identity import DeviceIdentityService
from npcreate_studio.services.error_reporter import ErrorReporter
from npcreate_studio.services.license_client import LicenseClient


def _print_step(num: int, text: str) -> None:
    print(f"\n[{num}] {text}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8088")
    ap.add_argument("--license-key", required=True)
    ap.add_argument("--api-key", required=True, help="X-API-Key value for /error-reports")
    ap.add_argument("--app-version", default="2.4.0")
    args = ap.parse_args()

    client = LicenseClient(base_url=args.base_url, app_version=args.app_version)

    _print_step(1, "Generate PC device identity")
    identity = DeviceIdentityService().pc_identity()
    print(f"     device_type     : {identity.device_type.value}")
    print(f"     fingerprint_hash: {identity.fingerprint_hash[:32]}…  (sha256, 64 chars)")
    print(f"     label           : {identity.label}")

    _print_step(2, "Activate license")
    result = client.activate(args.license_key, identity)
    print(f"     license_id  : {result.license_id}")
    print(f"     status      : {result.status.value}")
    print(f"     device_id   : {result.device_id}")
    print(f"     access_token: {result.activation_token[:32]}… (Bearer JWT-like)")
    print(f"     refresh tok : {result.refresh_token[:32]}… (32+ chars opaque)")

    _print_step(3, "Heartbeat (access token)")
    hb = client.heartbeat(result.activation_token)
    print(f"     server_time : {hb['server_time']}")
    print(f"     expires_at  : {hb['expires_at']}")

    _print_step(4, "Fetch news (access token)")
    items = client.fetch_news(result.activation_token)
    print(f"     news items  : {len(items)} (none seeded; ok)")

    _print_step(5, "Rotate refresh token")
    rotated = client.refresh(result.refresh_token)
    print(f"     new access  : {rotated.access_token[:32]}…")
    print(f"     new refresh : {rotated.refresh_token[:32]}…")
    print(f"     expires_at  : {rotated.expires_at}")

    _print_step(6, "Heartbeat with newly-rotated access token")
    hb2 = client.heartbeat(rotated.access_token)
    print(f"     server_time : {hb2['server_time']} (still active)")

    _print_step(7, "Submit error report (verifies X-API-Key path)")
    settings = Settings(license_server_url=args.base_url, app_api_key=args.api_key, app_version=args.app_version)
    reporter = ErrorReporter(settings)
    try:
        raise RuntimeError("Demo crash from e2e_client_demo")
    except RuntimeError as exc:
        payload = reporter.build_payload(exc, title="E2E demo", metadata={"flow": "demo"})

    import asyncio
    resp = asyncio.run(reporter.submit(payload))
    print(f"     report_id   : {resp.get('report_id', '?')}")
    print(f"     ok          : {resp.get('ok')}")

    print("\nALL E2E STEPS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

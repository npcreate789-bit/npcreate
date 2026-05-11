from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import time
import urllib.request


def main() -> None:
    ap = argparse.ArgumentParser(description="Send a signed test payment webhook to the backend")
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--secret", required=True)
    ap.add_argument("--provider", default="manual")
    ap.add_argument("--event-id", default="")
    ap.add_argument("--provider-payment-id", required=True)
    ap.add_argument("--provider-subscription-id", default="")
    ap.add_argument("--license-id", default="")
    ap.add_argument("--amount-satangs", type=int, default=0)
    args = ap.parse_args()
    body = {
        "id": args.event_id or f"evt_test_{int(time.time())}",
        "type": "payment.succeeded",
        "data": {
            "provider_payment_id": args.provider_payment_id,
            "provider_subscription_id": args.provider_subscription_id,
            "license_id": args.license_id,
            "amount_satangs": args.amount_satangs,
            "currency": "THB",
        },
    }
    payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(args.secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        args.base_url.rstrip("/") + f"/api/v1/webhooks/payments/{args.provider}",
        data=payload,
        headers={"Content-Type": "application/json", "X-NP-Signature": "sha256=" + sig},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        print(resp.read().decode("utf-8"))


if __name__ == "__main__":
    main()

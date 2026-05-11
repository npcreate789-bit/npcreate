"""Create or link a monthly payment subscription via direct DB access.

Server-side maintenance script. Use on the same host as the backend.
"""
from __future__ import annotations

import argparse
import json

from npcreate_backend.billing import create_subscription
from npcreate_backend.db import connect, migrate
from npcreate_backend.security import parse_dt
from npcreate_backend.settings import BackendSettings


def main() -> None:
    ap = argparse.ArgumentParser(description="Create a subscription for an NP Create license via direct DB access")
    ap.add_argument("--license-id", required=True)
    ap.add_argument("--provider", default="manual")
    ap.add_argument("--provider-customer-id", default="")
    ap.add_argument("--provider-subscription-id", required=True)
    ap.add_argument("--amount-satangs", type=int, default=0)
    ap.add_argument("--currency", default="THB")
    ap.add_argument("--next-renewal-at", default="", help="Optional ISO datetime, e.g. 2026-06-11T00:00:00+00:00")
    ap.add_argument("--actor", default="cli")
    ap.add_argument("--database-url", default="")
    ap.add_argument("--database-path", default="")
    args = ap.parse_args()

    settings = BackendSettings()
    target = args.database_url or args.database_path or settings.db_target
    conn = connect(target)
    migrate(conn)

    next_renewal = parse_dt(args.next_renewal_at) if args.next_renewal_at else None
    sub_id = create_subscription(
        conn,
        license_id=args.license_id,
        provider=args.provider,
        provider_customer_id=args.provider_customer_id,
        provider_subscription_id=args.provider_subscription_id,
        amount_satangs=args.amount_satangs,
        currency=args.currency,
        next_renewal_at=next_renewal,
        actor_id=args.actor,
    )
    conn.commit()
    print(json.dumps({"subscription_id": sub_id, "license_id": args.license_id}, ensure_ascii=False))


if __name__ == "__main__":
    main()

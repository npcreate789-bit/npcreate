"""Create an NP Create monthly license directly via the backend database.

This script is for server-side maintenance only. It connects to the same
database as the backend service (via NPCREATE_BACKEND_DATABASE_URL or
NPCREATE_BACKEND_DATABASE_PATH) and inserts the license row.

Run on the same host as the backend, e.g.:

    PYTHONPATH=src python scripts/admin_create_license.py \
        --customer-name "Acme Co" --months 1
"""
from __future__ import annotations

import argparse
import json
import secrets
from datetime import timedelta

from npcreate_backend.billing import default_device_policies, upsert_device_policies
from npcreate_backend.db import connect, migrate
from npcreate_backend.security import hash_license_key, iso, new_license_key, utcnow
from npcreate_backend.settings import BackendSettings


def main() -> None:
    ap = argparse.ArgumentParser(description="Create NP Create monthly license via direct DB access")
    ap.add_argument("--customer-name", required=True)
    ap.add_argument("--customer-contact", default="")
    ap.add_argument("--months", type=int, default=1)
    ap.add_argument("--max-pc", type=int, default=1)
    ap.add_argument("--max-phone", type=int, default=1)
    ap.add_argument("--actor", default="cli", help="audit actor id for the audit log entry")
    ap.add_argument("--device-policies-json", default="", help='Optional JSON list, e.g. [{"device_type":"pc","max_devices":2}]')
    ap.add_argument("--database-url", default="")
    ap.add_argument("--database-path", default="")
    args = ap.parse_args()

    settings = BackendSettings()
    target = args.database_url or args.database_path or settings.db_target
    conn = connect(target)
    migrate(conn)

    raw_key = new_license_key()
    now = utcnow()
    expires_at = now + timedelta(days=31 * args.months)
    license_id = "lic_" + secrets.token_urlsafe(18)

    if args.device_policies_json:
        policies = json.loads(args.device_policies_json)
    else:
        policies = default_device_policies(args.max_pc, args.max_phone)

    conn.execute(
        """
        INSERT INTO licenses(
            license_id, key_hash, customer_name, customer_contact, status, plan,
            starts_at, expires_at, max_pc_devices, max_phone_devices,
            features_json, notes, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            license_id,
            hash_license_key(raw_key, settings.key_pepper),
            args.customer_name,
            args.customer_contact,
            "active",
            "monthly",
            iso(now),
            iso(expires_at),
            args.max_pc,
            args.max_phone,
            "[]",
            "",
            iso(now),
            iso(now),
        ),
    )
    upsert_device_policies(conn, license_id, policies, actor=args.actor)
    conn.commit()

    print(json.dumps({
        "license_id": license_id,
        "license_key": raw_key,
        "expires_at": iso(expires_at),
        "customer_name": args.customer_name,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

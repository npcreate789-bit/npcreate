from __future__ import annotations

import argparse
import secrets
from pathlib import Path

from npcreate_backend.admin_security import hash_password, new_mfa_secret, otpauth_uri
from npcreate_backend.auth import VALID_ROLES
from npcreate_backend.db import connect, migrate
from npcreate_backend.security import iso, utcnow
from npcreate_backend.settings import BackendSettings


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an Admin user with MFA secret")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--name", default="Admin")
    parser.add_argument("--role", default="admin", choices=list(VALID_ROLES))
    parser.add_argument("--database-url", default="")
    parser.add_argument("--database-path", default="")
    args = parser.parse_args()
    settings = BackendSettings()
    target = args.database_url or args.database_path or settings.db_target
    conn = connect(target)
    migrate(conn)
    admin_id = "adm_" + secrets.token_urlsafe(18)
    secret = new_mfa_secret()
    now = iso(utcnow())
    conn.execute(
        """
        INSERT INTO admin_users(admin_id, email, display_name, password_hash, mfa_secret, mfa_enabled, role, status, created_at, updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (admin_id, args.email.strip().lower(), args.name, hash_password(args.password), secret, 1, args.role, "active", now, now),
    )
    conn.commit()
    print("Admin created:", args.email, "role:", args.role)
    print("MFA secret:", secret)
    print("Authenticator URI:", otpauth_uri(issuer="NP Create", email=args.email.strip().lower(), secret=secret))


if __name__ == "__main__":
    main()

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

SCHEMA_VERSION = 3


class ConnectionLike(Protocol):
    def execute(self, sql: str, params: Iterable[object] = ()) -> Any: ...
    def executescript(self, sql: str) -> Any: ...
    def commit(self) -> None: ...
    def close(self) -> None: ...


class PgConnection:
    """Tiny psycopg adapter so existing route code can keep sqlite-style '?' params.

    This is a bridge for the refactor. For a large system, migrate routes to a
    proper repository layer or SQLAlchemy. It still gives production deployments
    a real PostgreSQL backend instead of local SQLite.
    """

    def __init__(self, url: str) -> None:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("PostgreSQL requires dependency: psycopg[binary]") from exc
        self._psycopg = psycopg
        self._conn = psycopg.connect(url, row_factory=dict_row)
        self._conn.autocommit = False

    def execute(self, sql: str, params: Iterable[object] = ()):
        converted = sql.replace("?", "%s")
        return self._conn.execute(converted, tuple(params))

    def executescript(self, sql: str):
        for statement in [s.strip() for s in sql.split(";") if s.strip()]:
            self.execute(statement)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> PgConnection:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc:
            self._conn.rollback()
        else:
            self._conn.commit()
        self.close()


SQLITE_SCHEMA = r"""
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS licenses (
    license_id TEXT PRIMARY KEY,
    key_hash TEXT NOT NULL UNIQUE,
    customer_name TEXT NOT NULL,
    customer_contact TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    plan TEXT NOT NULL DEFAULT 'monthly',
    starts_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    max_pc_devices INTEGER NOT NULL DEFAULT 1,
    max_phone_devices INTEGER NOT NULL DEFAULT 1,
    features_json TEXT NOT NULL DEFAULT '[]',
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS device_policies (
    policy_id TEXT PRIMARY KEY,
    license_id TEXT NOT NULL REFERENCES licenses(license_id) ON DELETE CASCADE,
    device_type TEXT NOT NULL,
    max_devices INTEGER NOT NULL DEFAULT 1 CHECK(max_devices >= 0 AND max_devices <= 200),
    binding_mode TEXT NOT NULL DEFAULT 'admin_release_only',
    fingerprint_required INTEGER NOT NULL DEFAULT 1,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(license_id, device_type)
);

CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    license_id TEXT NOT NULL REFERENCES licenses(license_id) ON DELETE CASCADE,
    device_type TEXT NOT NULL,
    fingerprint_hash TEXT NOT NULL,
    label TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'bound',
    bound_at TEXT NOT NULL,
    last_seen_at TEXT,
    released_at TEXT,
    released_by TEXT,
    release_reason TEXT,
    UNIQUE(license_id, device_type, fingerprint_hash)
);

CREATE TABLE IF NOT EXISTS release_requests (
    request_id TEXT PRIMARY KEY,
    license_id TEXT NOT NULL REFERENCES licenses(license_id) ON DELETE CASCADE,
    device_id TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    requested_at TEXT NOT NULL,
    resolved_at TEXT,
    resolved_by TEXT
);

CREATE TABLE IF NOT EXISTS subscriptions (
    subscription_id TEXT PRIMARY KEY,
    license_id TEXT NOT NULL REFERENCES licenses(license_id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    provider_customer_id TEXT DEFAULT '',
    provider_subscription_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    billing_cycle TEXT NOT NULL DEFAULT 'monthly',
    amount_satangs INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'THB',
    next_renewal_at TEXT,
    last_payment_at TEXT,
    grace_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(provider, provider_subscription_id)
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id TEXT PRIMARY KEY,
    license_id TEXT REFERENCES licenses(license_id) ON DELETE SET NULL,
    subscription_id TEXT REFERENCES subscriptions(subscription_id) ON DELETE SET NULL,
    provider TEXT NOT NULL,
    provider_payment_id TEXT NOT NULL,
    provider_subscription_id TEXT DEFAULT '',
    status TEXT NOT NULL,
    amount_satangs INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'THB',
    paid_at TEXT,
    raw_payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(provider, provider_payment_id)
);

CREATE TABLE IF NOT EXISTS payment_events (
    event_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    external_event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    signature_valid INTEGER NOT NULL DEFAULT 0,
    payload_hash TEXT NOT NULL,
    processing_status TEXT NOT NULL DEFAULT 'received',
    error TEXT DEFAULT '',
    received_at TEXT NOT NULL,
    processed_at TEXT,
    UNIQUE(provider, external_event_id)
);

CREATE TABLE IF NOT EXISTS audit_logs (
    audit_id TEXT PRIMARY KEY,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    ip_address TEXT DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS news (
    news_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    audience TEXT NOT NULL DEFAULT 'all',
    published_at TEXT NOT NULL,
    expires_at TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS update_manifests (
    update_id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'stable',
    mandatory INTEGER NOT NULL DEFAULT 0,
    download_url TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    signature TEXT NOT NULL,
    release_notes TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1,
    published_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_users (
    admin_id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    mfa_secret TEXT NOT NULL,
    mfa_enabled INTEGER NOT NULL DEFAULT 1,
    role TEXT NOT NULL DEFAULT 'admin',
    status TEXT NOT NULL DEFAULT 'active',
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS admin_sessions (
    session_id TEXT PRIMARY KEY,
    admin_id TEXT NOT NULL REFERENCES admin_users(admin_id) ON DELETE CASCADE,
    session_hash TEXT NOT NULL UNIQUE,
    csrf_token TEXT NOT NULL,
    ip_address TEXT DEFAULT '',
    user_agent TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    token_id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    license_id TEXT NOT NULL REFERENCES licenses(license_id) ON DELETE CASCADE,
    device_id TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    rotated_to TEXT,
    revoked_at TEXT,
    revoke_reason TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS error_reports (
    report_id TEXT PRIMARY KEY,
    license_id TEXT DEFAULT '',
    device_id TEXT DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'error',
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    traceback TEXT DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    app_version TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
);

CREATE INDEX IF NOT EXISTS idx_device_policies_license_type ON device_policies(license_id, device_type);
CREATE INDEX IF NOT EXISTS idx_devices_license_status ON devices(license_id, status);
CREATE INDEX IF NOT EXISTS idx_devices_license_type_status ON devices(license_id, device_type, status);
CREATE INDEX IF NOT EXISTS idx_subscriptions_license_status ON subscriptions(license_id, status);
CREATE INDEX IF NOT EXISTS idx_subscriptions_next_renewal ON subscriptions(status, next_renewal_at, grace_until);
CREATE INDEX IF NOT EXISTS idx_payments_license_created ON payments(license_id, created_at);
CREATE INDEX IF NOT EXISTS idx_payment_events_status ON payment_events(processing_status, received_at);
CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_logs(target_type, target_id, created_at);
CREATE INDEX IF NOT EXISTS idx_admin_sessions_hash ON admin_sessions(session_hash, expires_at);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_device ON refresh_tokens(device_id, revoked_at);
CREATE INDEX IF NOT EXISTS idx_error_reports_status ON error_reports(status, created_at);
CREATE INDEX IF NOT EXISTS idx_news_active_pub ON news(is_active, published_at);
CREATE INDEX IF NOT EXISTS idx_updates_channel_active ON update_manifests(channel, is_active, published_at);
"""


def _postgres_schema() -> str:
    return SQLITE_SCHEMA.replace("INTEGER PRIMARY KEY", "INTEGER PRIMARY KEY").replace("DEFAULT CURRENT_TIMESTAMP", "DEFAULT CURRENT_TIMESTAMP")


def connect(target: str | Path) -> sqlite3.Connection | PgConnection:
    target_str = str(target)
    if target_str.startswith(("postgresql://", "postgres://")):
        return PgConnection(target_str)
    db_path = Path(target)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def migrate(conn: sqlite3.Connection | PgConnection) -> None:
    conn.executescript(SQLITE_SCHEMA)
    try:
        conn.execute("ALTER TABLE subscriptions ADD COLUMN grace_until TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE admin_users ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")
    except Exception:
        pass
    if isinstance(conn, PgConnection):
        conn.execute("INSERT INTO schema_migrations(version) VALUES (?) ON CONFLICT (version) DO NOTHING", (SCHEMA_VERSION,))
    else:
        conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (SCHEMA_VERSION,))
    conn.commit()


def one(conn: sqlite3.Connection | PgConnection, sql: str, params: Iterable[object] = ()) -> Any | None:
    return conn.execute(sql, tuple(params)).fetchone()


def all_rows(conn: sqlite3.Connection | PgConnection, sql: str, params: Iterable[object] = ()) -> list[Any]:
    return list(conn.execute(sql, tuple(params)).fetchall())

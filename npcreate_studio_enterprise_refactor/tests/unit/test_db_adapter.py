"""Tests for the cross-DB adapter: placeholder rewriting + unified IntegrityError.

Postgres integration tests are gated on TEST_POSTGRES_URL and skipped otherwise,
so this file works in CI without a database service.
"""
from __future__ import annotations

import os

import pytest

from npcreate_backend.db import (
    INTEGRITY_ERRORS,
    PgConnection,
    _qmark_to_pyformat,
    connect,
    migrate,
    one,
)

# -- placeholder rewriter ----------------------------------------------------


def test_qmark_to_pyformat_basic():
    assert _qmark_to_pyformat("SELECT * FROM t WHERE x=? AND y=?") == "SELECT * FROM t WHERE x=%s AND y=%s"


def test_qmark_to_pyformat_preserves_question_inside_single_quoted_string():
    sql = "INSERT INTO t(msg, x) VALUES('what?', ?)"
    assert _qmark_to_pyformat(sql) == "INSERT INTO t(msg, x) VALUES('what?', %s)"


def test_qmark_to_pyformat_preserves_escaped_quotes_inside_literal():
    sql = "SELECT 'it''s ?' AS s, x FROM t WHERE x=?"
    assert _qmark_to_pyformat(sql) == "SELECT 'it''s ?' AS s, x FROM t WHERE x=%s"


def test_qmark_to_pyformat_preserves_question_inside_double_quoted_identifier():
    sql = 'SELECT "col?" FROM t WHERE x=?'
    assert _qmark_to_pyformat(sql) == 'SELECT "col?" FROM t WHERE x=%s'


def test_qmark_to_pyformat_doubles_bare_percent_for_psycopg():
    sql = "SELECT * FROM t WHERE name LIKE 'foo%' AND x=?"
    out = _qmark_to_pyformat(sql)
    # `%` inside literal stays as-is; outside literal is doubled.
    assert "LIKE 'foo%'" in out
    assert out.endswith("AND x=%s")


def test_qmark_to_pyformat_doubles_percent_outside_literal():
    assert _qmark_to_pyformat("SELECT 100 % 7") == "SELECT 100 %% 7"


# -- INTEGRITY_ERRORS includes both backends when both are importable -------


def test_integrity_errors_includes_sqlite():
    import sqlite3

    assert sqlite3.IntegrityError in INTEGRITY_ERRORS


def test_integrity_errors_includes_psycopg_when_available():
    try:
        import psycopg.errors as pg_errors
    except ImportError:
        pytest.skip("psycopg not installed")
    assert pg_errors.IntegrityError in INTEGRITY_ERRORS


# -- Postgres integration ----------------------------------------------------

POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL", "")


@pytest.fixture
def pg_conn():
    if not POSTGRES_URL:
        pytest.skip("TEST_POSTGRES_URL not set; skipping Postgres integration tests")
    conn = connect(POSTGRES_URL)
    assert isinstance(conn, PgConnection)
    # Wipe any leftover state from previous runs.
    for table in [
        "refresh_tokens", "error_reports", "audit_logs", "release_requests",
        "payment_events", "payments", "subscriptions", "devices", "device_policies",
        "news", "update_manifests", "admin_sessions", "admin_users",
        "licenses", "schema_migrations",
    ]:
        try:
            conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
        except Exception:
            conn.rollback()
    conn.commit()
    yield conn
    conn.close()


@pytest.mark.postgres
def test_postgres_migrate_creates_all_tables(pg_conn):
    migrate(pg_conn)
    pg_conn.commit()
    # All app tables must exist after migrate.
    rows = pg_conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name"
    ).fetchall()
    tables = {r["table_name"] for r in rows}
    assert {"licenses", "devices", "admin_users", "admin_sessions",
            "subscriptions", "payments", "refresh_tokens",
            "schema_migrations"}.issubset(tables)


@pytest.mark.postgres
def test_postgres_migrate_is_idempotent(pg_conn):
    migrate(pg_conn)
    pg_conn.commit()
    migrate(pg_conn)  # must not raise on duplicate-column ALTER
    pg_conn.commit()


@pytest.mark.postgres
def test_postgres_qmark_placeholders_work_with_real_insert(pg_conn):
    migrate(pg_conn)
    pg_conn.commit()
    pg_conn.execute(
        """
        INSERT INTO licenses(license_id,key_hash,customer_name,status,plan,starts_at,expires_at,
                             max_pc_devices,max_phone_devices,features_json,notes,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        ("lic_pg_test", "hash_pg", "C", "active", "monthly",
         "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z",
         1, 1, "[]", "", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    pg_conn.commit()
    row = one(pg_conn, "SELECT customer_name FROM licenses WHERE license_id=?", ("lic_pg_test",))
    assert row["customer_name"] == "C"


@pytest.mark.postgres
def test_postgres_unique_violation_raises_unified_integrity_error(pg_conn):
    migrate(pg_conn)
    pg_conn.commit()
    insert_sql = """
        INSERT INTO licenses(license_id,key_hash,customer_name,status,plan,starts_at,expires_at,
                             max_pc_devices,max_phone_devices,features_json,notes,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
    """
    params = ("lic_uniq", "hash_uniq", "C", "active", "monthly",
              "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z",
              1, 1, "[]", "", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
    pg_conn.execute(insert_sql, params)
    pg_conn.commit()
    with pytest.raises(INTEGRITY_ERRORS):
        pg_conn.execute(insert_sql, params)
    pg_conn.rollback()

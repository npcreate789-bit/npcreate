from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

SCHEMA_VERSION = 1

MIGRATIONS: dict[int, Iterable[str]] = {
    1: [
        """
        CREATE TABLE IF NOT EXISTS app_meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS shops (
          shop_id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          region TEXT NOT NULL DEFAULT 'TH',
          created_at INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS products (
          product_id TEXT PRIMARY KEY,
          shop_id TEXT NOT NULL REFERENCES shops(shop_id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          image_url TEXT DEFAULT '',
          created_at INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS orders (
          order_id TEXT PRIMARY KEY,
          shop_id TEXT NOT NULL REFERENCES shops(shop_id) ON DELETE CASCADE,
          amount_cents INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL,
          ordered_at INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS secure_items (
          key TEXT PRIMARY KEY,
          value BLOB NOT NULL,
          updated_at INTEGER NOT NULL
        )
        """,
    ]
}


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    migrate(conn)
    return conn


def current_version(conn: sqlite3.Connection) -> int:
    conn.execute("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    row = conn.execute("SELECT value FROM app_meta WHERE key='schema_version'").fetchone()
    return int(row["value"]) if row else 0


def migrate(conn: sqlite3.Connection) -> None:
    cur = current_version(conn)
    if cur > SCHEMA_VERSION:
        raise RuntimeError(f"database schema {cur} is newer than app supports {SCHEMA_VERSION}")
    for version in range(cur + 1, SCHEMA_VERSION + 1):
        with conn:
            for sql in MIGRATIONS[version]:
                conn.execute(sql)
            conn.execute(
                "INSERT OR REPLACE INTO app_meta(key, value) VALUES('schema_version', ?)",
                (str(version),),
            )

# NP Create Studio v2.5.0 — Enterprise Hardening Release

**Release date:** 2026-05-11
**Previous version:** v2.4.0

This release closes the Phase 1 production-readiness gaps from the Enterprise
Readiness Assessment (2026-05-11) and most of Phase 2, plus operational and
client-side hardening required to stand up a real staging pilot.

The system is now **ready for staging pilot** with real customers. Remaining
production blockers all require external context (merchant accounts, Windows
signing certificate, ops drills) — they are documented in §Known limits below.

---

## Highlights

- **3 backends commits + 1 bug fix** that closed every P0 hardening item we
  could fix without external context (5 of 7 P0s done).
- **CSRF, RBAC (5 roles), refresh-token rotation with reuse detection,
  structured logging, MFA backup codes, sliding admin idle timeout, refresh
  rate limit** — all wired and tested.
- **Test suite grew from 22 → 152 tests** (+ 4 Postgres integration tests
  running in CI). All pass on Python 3.11/3.12/3.13.
- **CI / Postgres / SBOM** pipeline added: lint + bandit + pytest + pip-audit +
  Postgres-16 integration + CycloneDX SBOM artifact, all green.
- **Admin Dashboard now has CRUD forms** for creating licenses, renewing,
  approving/rejecting release requests, publishing news, and publishing
  signed update manifests — directly from the browser, no CLI needed.
- **Client GUI** now wires the activate button to a real lifecycle service
  with encrypted token persistence and auto-refresh on 401.

---

## Breaking changes

None for client code paths that were already correct.
The following changes affect callers that depended on internal APIs:

1. **`POST /api/v1/admin/*`** now requires a `X-CSRF-Token` header (or
   `_csrf` form field) that matches the active admin session's CSRF token.
   - Browser admin dashboard forms send this automatically.
   - CLI scripts must use the new server-side direct-DB scripts (see
     `scripts/admin_create_license.py` etc.) — the `X-Admin-Token` JSON-API
     path is gone unless `allow_legacy_admin_token=true` is explicitly set.

2. **`POST /api/v1/error-reports`** (client → backend) now requires
   `X-API-Key` header. The endpoint moved from `/api/v1/public/error-reports`
   to `/api/v1/error-reports` to match the actual backend routing.

3. **`POST /api/v1/licenses/activate`** response shape:
   - `activation_token` is now a **short-lived access token (30 min)**.
   - `refresh_token` is no longer `null`; clients must persist it and call
     `POST /api/v1/auth/refresh` to rotate before the access token expires.
   - Old clients that ignore `refresh_token` will work until the first
     access token expires, then start getting 401 on heartbeat.

4. **Admin roles** are enforced. The default role for accounts created via
   `scripts/admin_create_user.py` is `admin`. Use `--role owner` for full
   access; other roles (`support`, `billing`, `viewer`) get a subset of POST
   endpoints. Existing single-role admins keep working because the migration
   defaults `role='admin'`.

---

## What's new

### Security (P0/P1 from assessment)

- **CSRF protection** on all admin POST/PUT/DELETE endpoints. Browser forms
  pass `_csrf` field; JSON callers pass `X-CSRF-Token` header. Method-aware
  (skip safe methods); legacy CLI token (when enabled) bypasses CSRF.
- **RBAC** with roles `owner / admin / support / billing / viewer`.
  Each admin POST endpoint declares its allowed roles via `require_role(...)`;
  `403 role 'X' not permitted` on mismatch.
- **Admin session idle timeout** (config `admin_session_idle_timeout_minutes`,
  default 30). Stored on `admin_sessions.last_activity_at`; updated on every
  authenticated request (sliding); also keeps the absolute 8-hour TTL.
- **Refresh token rotation** with **reuse detection**. Each rotation issues a
  new opaque refresh token (32 bytes) and revokes the old one. Re-using a
  rotated token revokes the entire chain for that device (treat as compromise).
- **MFA backup codes** (8 per admin, single-use). Generated and printed at
  account creation; admin can regenerate from `/admin/account` page. Login
  accepts a backup code in place of TOTP; consumed on first use.
- **Refresh endpoint rate limit** (`auth_refresh_rate_limit_per_minute`,
  default 30) — IP-based, mirrors the existing activation rate limit.
- **Audit log records the real admin_id** (not the literal string `"admin"`)
  for every mutating admin action. Includes `device.release`, `license.renew`,
  `subscription.create`, `news.publish`, `update.publish`, etc.

### Observability

- **Structured event logging** (`observability.log_event`) for all critical
  events: `admin.login_failed/success/logout`, `payment.failed/signature_rejected/processed`,
  `license.past_due/suspend_overdue/auto_renew/renew`, `device.released`,
  `release_request.approved/rejected`, `update.published`, `news.published`.
- JSON formatter when `NPCREATE_BACKEND_ENV=production`; plain dev formatter
  otherwise. Designed for direct ingestion into SIEM / log pipelines.
- **`/healthz` is now a real readiness probe**: runs `SELECT 1` against the
  configured database and returns `503 {db: "down"}` on failure.

### Persistence

- **PostgreSQL adapter hardening**: safe placeholder rewriter that skips `?`
  inside string literals and quoted identifiers (replaces the naive
  `sql.replace("?", "%s")` that could corrupt SQL containing literal `?`).
  Unified `INTEGRITY_ERRORS` tuple so unique-constraint catches work on both
  SQLite and psycopg. `ALTER TABLE … ADD COLUMN IF NOT EXISTS` for Postgres.
- **Refresh-token table** + index, **admin backup codes table** + index,
  `admin_sessions.last_activity_at` column, `admin_users.role` column —
  all applied via idempotent `_add_column_if_missing` migrations.
- **CI runs full Postgres integration** (Postgres 16 service container) to
  verify migrations + placeholder rewriting + unique-violation flow.

### Admin Dashboard

- **Create license form** (`/admin/licenses`) — the freshly generated
  license key is displayed once in a banner (the system stores only the hash).
- **Renew license** per-row form with month selector.
- **Approve / reject release requests** with a single click (CSRF protected;
  approval also revokes any active refresh tokens for the released device).
- **Publish news** (`/admin/news`) with severity selector and audience field.
- **Publish signed update manifest** (`/admin/updates`) that signs with
  `NPCREATE_BACKEND_ED25519_PRIVATE_KEY_HEX` server-side; UI warns when key
  is missing so the page renders but the button is disabled.
- **Pagination, filter, search** on every list endpoint (`licenses`,
  `payments`, `devices`, `release-requests`, `audit-logs`, `payment-events`,
  `subscriptions`, `news`, `updates`). Limit clamped to `[1, 200]`.
  Search uses parameterized LIKE with `like_escape` to neutralize `%` / `_`.
- **Account page** (`/admin/account`) — change password, view backup-code
  count, regenerate backup codes (shown once via redirect query).

### Client (`npcreate_studio`)

- **`SecureStore.save_tokens / get_tokens / clear_tokens`** — encrypted JSON
  in `app_data_dir/tokens.enc` (atomic write via `.tmp + replace`; corrupt
  file gracefully returns `None`).
- **`LicenseLifecycleService`** orchestrates activate / heartbeat / refresh /
  clear. Proactive rotation when access token is within 2 minutes of expiry;
  reactive rotation + retry once on 401 heartbeat.
- **Client GUI license page** "Activate เครื่องนี้" button is now wired:
  enter key → service.activate → toast feedback → status pill updates to
  "Activated" with license_id / device_id / expiry rendered from the
  persisted state.
- **`ErrorReporter`** sends `X-API-Key` and uses the correct
  `/api/v1/error-reports` path (was `/api/v1/public/error-reports`).

### Tooling and release pipeline

- **`docker-compose.yml`** + **`Dockerfile`** — `docker compose up --build`
  brings up backend + Postgres 16 in one command, including healthchecks
  and a non-root runtime user.
- **`requirements.txt` / `requirements-dev.txt`** locked via `pip-compile`.
  Production deps re-bumped to close known CVEs:
  - `cryptography` ≥ 46.0.7 (closes CVE-2026-26007 / 34073 / 39892)
  - `pillow` ≥ 12.2 (closes CVE-2026-42310 / 42311)
  - `pytest` ≥ 9 (closes CVE-2025-71176)
- **GitHub Actions CI** at `.github/workflows/ci.yml` (repo root) runs:
  - `lint-test-audit` matrix Python 3.11/3.12/3.13:
    ruff + mypy (soft) + bandit + pytest with coverage + pip-audit
  - `postgres-integration`: Postgres 16 service + `@pytest.mark.postgres` tests
  - `sbom`: CycloneDX 1.5 SBOM uploaded as artifact (90-day retention)
- **`scripts/run_security_checks.sh`** — local mirror of the CI pipeline.

### Testing

- 22 → 152 unit tests, all green on 3 Python versions and Postgres 16.
- Coverage now includes payment providers (Omise / 2C2P / GB Prime Pay),
  refresh-token rotation + reuse detection, admin login with backup codes,
  HTML form CSRF + RBAC, pagination + LIKE escape, lifecycle auto-refresh.
- `scripts/e2e_client_demo.py` — driver that exercises the activate →
  heartbeat → refresh → news → release flow through the real
  `LicenseClient` / `ErrorReporter` against a running backend.

---

## Upgrade notes

### Schema migrations (idempotent on startup)

- New tables: `refresh_tokens`, `admin_backup_codes`.
- New columns: `admin_sessions.last_activity_at`, `admin_users.role`,
  `subscriptions.grace_until` (was already added in v2.4.0).
- Migrations run automatically on `migrate(conn)` at startup; SQLite uses
  try/except, Postgres uses `IF NOT EXISTS`. Safe to roll forward.

### New environment variables

```bash
NPCREATE_BACKEND_ACTIVATION_ACCESS_TTL_MINUTES=30      # short access TTL
NPCREATE_BACKEND_ADMIN_SESSION_IDLE_TIMEOUT_MINUTES=30 # admin idle
NPCREATE_BACKEND_AUTH_REFRESH_RATE_LIMIT_PER_MINUTE=30 # refresh rate limit
NPCREATE_APP_API_KEY=...                               # client: send w/ error report
```

### Production checklist (the changes that matter)

1. Rotate any admin secrets that started with `dev_`/`CHANGE_ME_`.
2. Re-create admin users with `scripts/admin_create_user.py --role owner`
   to receive backup codes (existing admins are upgraded to role `admin`).
3. Set `NPCREATE_BACKEND_ED25519_PRIVATE_KEY_HEX` if you plan to publish
   updates through the dashboard UI.
4. Point clients at the new release; old clients keep activating but will
   only have a 30-minute access token until they upgrade to use the refresh
   flow.
5. Make sure your load balancer / k8s readiness probe hits `/healthz` —
   it now actually verifies the database.

---

## Known limits (not in v2.5.0 — require external context)

These items are tracked but cannot ship until we have the corresponding
external resources:

- **P0 #6 — Payment merchant verification.** Adapters are written and unit
  tested with synthetic HMAC signatures, but real Stripe / Omise / 2C2P /
  GB Prime Pay accounts are needed to validate the live signature schemes
  end-to-end against each provider's sandbox.
- **P0 #7 — Windows installer + code-signing.** Build/sign scripts exist
  but the Inno Setup AppId is still a scaffold value, and code-signing
  requires a Windows host and a real OV/EV certificate.
- **P1 #4 — Windows DPAPI for client secret storage.** `SecureStore` still
  falls back to a Fernet key in `app_data_dir/master.key`. DPAPI binding
  needs a Windows build environment.
- **P1 #7 — Backup / restore drill.** Needs production-like Postgres and an
  ops runbook; out of scope for this code release.

---

## Acknowledgements

This release was built collaboratively with Claude Opus 4.7 (1M context).
See git log for per-commit attribution.

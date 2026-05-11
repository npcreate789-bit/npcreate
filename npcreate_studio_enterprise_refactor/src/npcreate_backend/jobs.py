from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from .billing import audit_log
from .db import all_rows, connect, migrate
from .observability import log_event
from .security import iso, parse_dt, utcnow
from .settings import BackendSettings

log = logging.getLogger(__name__)


def run_billing_maintenance(settings: BackendSettings) -> dict[str, int]:
    conn = connect(settings.db_target)
    migrate(conn)
    now = utcnow()
    now_iso = iso(now)
    past_due = 0
    suspended = 0
    rows = all_rows(conn, "SELECT * FROM subscriptions WHERE status IN ('active','past_due')")
    for sub in rows:
        next_renewal = sub["next_renewal_at"]
        if not next_renewal:
            continue
        due = parse_dt(next_renewal)
        grace_until = sub["grace_until"]
        if due < now and sub["status"] == "active":
            grace = iso(now + timedelta(days=settings.payment_grace_days))
            conn.execute("UPDATE subscriptions SET status='past_due', grace_until=?, updated_at=? WHERE subscription_id=?", (grace, now_iso, sub["subscription_id"]))
            conn.execute("UPDATE licenses SET status='past_due', updated_at=? WHERE license_id=?", (now_iso, sub["license_id"]))
            audit_log(conn, actor_type="job", actor_id="billing", action="subscription.past_due", target_type="subscription", target_id=sub["subscription_id"])
            log_event(
                "license.past_due",
                level=logging.WARNING,
                license_id=sub["license_id"],
                subscription_id=sub["subscription_id"],
                grace_until=grace,
            )
            past_due += 1
        elif sub["status"] == "past_due":
            grace_dt = parse_dt(grace_until) if grace_until else due + timedelta(days=settings.payment_grace_days)
            if grace_dt < now:
                conn.execute("UPDATE subscriptions SET status='suspended', updated_at=? WHERE subscription_id=?", (now_iso, sub["subscription_id"]))
                conn.execute("UPDATE licenses SET status='suspended', updated_at=? WHERE license_id=?", (now_iso, sub["license_id"]))
                audit_log(conn, actor_type="job", actor_id="billing", action="license.suspend_overdue", target_type="license", target_id=sub["license_id"])
                log_event(
                    "license.suspend_overdue",
                    level=logging.ERROR,
                    license_id=sub["license_id"],
                    subscription_id=sub["subscription_id"],
                )
                suspended += 1
    conn.commit()
    return {"past_due": past_due, "suspended": suspended}


async def billing_job_loop(settings: BackendSettings) -> None:
    while True:
        try:
            result = run_billing_maintenance(settings)
            if result["past_due"] or result["suspended"]:
                log.info("billing maintenance: %s", result)
        except Exception:
            log.exception("billing maintenance failed")
        await asyncio.sleep(settings.billing_job_interval_minutes * 60)

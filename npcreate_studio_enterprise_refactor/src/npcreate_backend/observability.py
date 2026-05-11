"""Structured logging for critical security and billing events.

Production deployments should ship logs to a SIEM/log pipeline. This module
emits one record per critical event with a stable `event` name and structured
fields, so monitors can alert on patterns like repeated `admin.login_failed`
or `payment.signature_rejected` without parsing free-form strings.
"""
from __future__ import annotations

import json
import logging
from typing import Any

EVENT_LOGGER_NAME = "npcreate.events"
_event_log = logging.getLogger(EVENT_LOGGER_NAME)

CRITICAL_EVENTS = frozenset({
    "admin.login_failed",
    "admin.login_success",
    "admin.logout",
    "payment.signature_rejected",
    "payment.failed",
    "payment.processed",
    "payment.duplicate",
    "license.auto_renew",
    "license.suspend_overdue",
    "license.past_due",
    "license.renew",
    "device.released",
    "release_request.approved",
    "release_request.rejected",
    "update.published",
    "news.published",
    "subscription.created",
    "device_policy.upserted",
})


class JsonFormatter(logging.Formatter):
    """Emit log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in payload:
                continue
            if key in {"args", "msg", "exc_info", "exc_text", "stack_info", "name", "levelname",
                        "levelno", "pathname", "filename", "module", "lineno", "funcName",
                        "created", "asctime", "msecs", "relativeCreated", "thread",
                        "threadName", "process", "processName", "taskName"}:
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except TypeError:
                payload[key] = repr(value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(env: str, *, level: str = "INFO") -> None:
    """Configure root + event logger handlers idempotently."""
    root = logging.getLogger()
    if getattr(configure_logging, "_done", False):
        return
    root.setLevel(level)
    handler = logging.StreamHandler()
    if env == "production":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    configure_logging._done = True  # type: ignore[attr-defined]


def log_event(event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    """Emit a structured event log record.

    `event` is the canonical event name (snake_case with dots, e.g.
    `admin.login_failed`). Additional fields go into log record extras so they
    are picked up by JsonFormatter and ignored by plain formatters.
    """
    if event not in CRITICAL_EVENTS:
        # Allow ad-hoc events but make typos visible in dev.
        _event_log.debug("unregistered event name: %s", event)
    _event_log.log(level, event, extra={"event": event, **{k: _safe(v) for k, v in fields.items()}})


def _safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return repr(value)

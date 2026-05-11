from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import HTTPException, Request, status

from .settings import BackendSettings


@dataclass(frozen=True)
class NormalizedPaymentEvent:
    provider: str
    external_event_id: str
    event_type: str
    provider_payment_id: str
    provider_subscription_id: str
    amount_satangs: int
    currency: str
    raw_data: dict[str, Any]


class PaymentProviderAdapter(Protocol):
    provider: str
    async def verify(self, request: Request, payload: bytes, settings: BackendSettings) -> bool: ...
    def normalize(self, payload: bytes) -> dict[str, Any]: ...


def _safe_json(payload: bytes) -> dict[str, Any]:
    try:
        body = json.loads(payload.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid json") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="payload must be json object")
    return body


def _hmac_hex(secret: str, signed_payload: bytes, signature: str) -> bool:
    if not secret or not signature:
        return False
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)


class StripeAdapter:
    provider = "stripe"

    async def verify(self, request: Request, payload: bytes, settings: BackendSettings) -> bool:
        secret = settings.stripe_webhook_secret or settings.payment_webhook_secret
        header = request.headers.get("stripe-signature", "")
        parts = dict(item.split("=", 1) for item in header.split(",") if "=" in item)
        timestamp = parts.get("t", "")
        sig = parts.get("v1", "")
        if not timestamp or not sig:
            return False
        try:
            if abs(time.time() - int(timestamp)) > settings.payment_webhook_max_age_seconds:
                return False
        except ValueError:
            return False
        signed = f"{timestamp}.".encode() + payload
        return _hmac_hex(secret, signed, sig)

    def normalize(self, payload: bytes) -> dict[str, Any]:
        body = _safe_json(payload)
        obj = body.get("data", {}).get("object", {}) if isinstance(body.get("data"), dict) else {}
        event_type = str(body.get("type", ""))
        successful = event_type in {"invoice.payment_succeeded", "checkout.session.completed", "customer.subscription.updated"}
        failed = event_type in {"invoice.payment_failed", "customer.subscription.deleted"}
        provider_subscription_id = str(obj.get("subscription") or obj.get("id") or "")
        amount = int(obj.get("amount_paid") or obj.get("amount_total") or obj.get("amount") or 0)
        currency = str(obj.get("currency") or "thb").upper()
        return {
            "id": body.get("id"),
            "type": "payment.succeeded" if successful else ("payment.failed" if failed else event_type),
            "data": {
                "provider_payment_id": obj.get("payment_intent") or obj.get("charge") or obj.get("id") or body.get("id"),
                "provider_subscription_id": provider_subscription_id,
                "amount_satangs": amount,
                "currency": currency,
                "raw_provider_type": event_type,
            },
        }


class OmiseAdapter:
    provider = "omise"

    async def verify(self, request: Request, payload: bytes, settings: BackendSettings) -> bool:
        secret = settings.omise_webhook_secret or settings.payment_webhook_secret
        signature = request.headers.get("omise-signature", "")
        timestamp = request.headers.get("omise-signature-timestamp", "")
        if not signature or not timestamp:
            return False
        try:
            if abs(time.time() - int(timestamp)) > settings.payment_webhook_max_age_seconds:
                return False
            key = base64.b64decode(secret) if secret else b""
        except Exception:
            return False
        signed = f"{timestamp}.".encode() + payload
        digest = hmac.new(key, signed, hashlib.sha256).hexdigest()
        return hmac.compare_digest(digest, signature)

    def normalize(self, payload: bytes) -> dict[str, Any]:
        body = _safe_json(payload)
        key = str(body.get("key") or body.get("type") or "")
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        charge = data.get("object") if isinstance(data.get("object"), dict) else data
        successful = key in {"charge.complete", "charge.succeeded"} or charge.get("status") == "successful"
        failed = key in {"charge.failed"} or charge.get("status") == "failed"
        return {
            "id": body.get("id") or data.get("id") or charge.get("id"),
            "type": "payment.succeeded" if successful else ("payment.failed" if failed else key),
            "data": {
                "provider_payment_id": charge.get("id") or data.get("id"),
                "provider_subscription_id": charge.get("metadata", {}).get("provider_subscription_id") or charge.get("metadata", {}).get("subscription_id") or charge.get("customer", ""),
                "amount_satangs": int(charge.get("amount") or 0),
                "currency": str(charge.get("currency") or "THB").upper(),
                "raw_provider_type": key,
            },
        }


class GenericHmacAdapter:
    def __init__(self, provider: str, secret_attr: str) -> None:
        self.provider = provider
        self.secret_attr = secret_attr

    async def verify(self, request: Request, payload: bytes, settings: BackendSettings) -> bool:
        secret = getattr(settings, self.secret_attr) or settings.payment_webhook_secret
        signature = request.headers.get("x-signature", "") or request.headers.get("x-webhook-signature", "")
        timestamp = request.headers.get("x-signature-timestamp", "")
        signed = payload
        if timestamp:
            try:
                if abs(time.time() - int(timestamp)) > settings.payment_webhook_max_age_seconds:
                    return False
            except ValueError:
                return False
            signed = f"{timestamp}.".encode() + payload
        return _hmac_hex(secret, signed, signature)

    def normalize(self, payload: bytes) -> dict[str, Any]:
        body = _safe_json(payload)
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        status_text = str(data.get("status") or body.get("status") or "").lower()
        successful = status_text in {"success", "successful", "paid", "approved", "completed"}
        failed = status_text in {"failed", "declined", "cancelled", "expired", "past_due"}
        return {
            "id": body.get("id") or body.get("event_id") or data.get("transaction_id") or data.get("referenceNo") or data.get("tranRef"),
            "type": "payment.succeeded" if successful else ("payment.failed" if failed else str(body.get("type") or "payment.updated")),
            "data": {
                "provider_payment_id": data.get("payment_id") or data.get("transaction_id") or data.get("referenceNo") or data.get("tranRef"),
                "provider_subscription_id": data.get("provider_subscription_id") or data.get("subscription_id") or data.get("reference_id") or data.get("customerReference"),
                "amount_satangs": int(data.get("amount_satangs") or data.get("amount") or 0),
                "currency": str(data.get("currency") or "THB").upper(),
            },
        }


ADAPTERS: dict[str, PaymentProviderAdapter] = {
    "stripe": StripeAdapter(),
    "omise": OmiseAdapter(),
    "2c2p": GenericHmacAdapter("2c2p", "twoc2p_webhook_secret"),
    "gbprimepay": GenericHmacAdapter("gbprimepay", "gbprimepay_webhook_secret"),
    "manual": GenericHmacAdapter("manual", "payment_webhook_secret"),
}


def get_adapter(provider: str) -> PaymentProviderAdapter:
    adapter = ADAPTERS.get(provider.lower())
    if not adapter:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported payment provider")
    return adapter

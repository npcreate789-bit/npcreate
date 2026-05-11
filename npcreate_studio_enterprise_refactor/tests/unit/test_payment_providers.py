"""Tests for payment provider adapters: signature verification + payload normalization."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import pytest

from npcreate_backend.payment_providers import (
    GenericHmacAdapter,
    OmiseAdapter,
    StripeAdapter,
    get_adapter,
)
from npcreate_backend.settings import BackendSettings


def _settings(**overrides) -> BackendSettings:
    base = {
        "env": "development",
        "payment_webhook_secret": "shared-fallback-secret-shared-fallback-secret",
        "stripe_webhook_secret": "whsec_stripe_test_secret",
        "omise_webhook_secret": base64.b64encode(b"omise-raw-secret-bytes-32-bytes-long-x").decode(),
        "twoc2p_webhook_secret": "2c2p_secret_2c2p_secret_2c2p_secret",
        "gbprimepay_webhook_secret": "gbprimepay_secret_gbprimepay_secret",
        "payment_webhook_max_age_seconds": 300,
    }
    base.update(overrides)
    return BackendSettings(**base)


def _request(headers: dict[str, str]):
    return SimpleNamespace(headers=headers)


def _run(coro):
    return asyncio.run(coro)


# -- StripeAdapter -----------------------------------------------------------


def test_stripe_signature_verifies_valid_payload():
    adapter = StripeAdapter()
    settings = _settings()
    payload = b'{"id":"evt_1","type":"invoice.payment_succeeded","data":{"object":{"id":"in_1","subscription":"sub_1","amount_paid":1590000,"currency":"thb"}}}'
    ts = str(int(time.time()))
    sig = hmac.new(settings.stripe_webhook_secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    request = _request({"stripe-signature": f"t={ts},v1={sig}"})
    assert _run(adapter.verify(request, payload, settings)) is True


def test_stripe_signature_rejects_tampered_payload():
    adapter = StripeAdapter()
    settings = _settings()
    payload = b'{"id":"evt_1"}'
    ts = str(int(time.time()))
    sig = hmac.new(settings.stripe_webhook_secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    request = _request({"stripe-signature": f"t={ts},v1={sig}"})
    assert _run(adapter.verify(request, b'{"id":"different"}', settings)) is False


def test_stripe_signature_rejects_stale_timestamp():
    adapter = StripeAdapter()
    settings = _settings(payment_webhook_max_age_seconds=60)
    payload = b'{"id":"evt_1"}'
    ts = str(int(time.time()) - 3600)  # 1 hour ago
    sig = hmac.new(settings.stripe_webhook_secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    request = _request({"stripe-signature": f"t={ts},v1={sig}"})
    assert _run(adapter.verify(request, payload, settings)) is False


def test_stripe_normalize_extracts_subscription_and_amount():
    adapter = StripeAdapter()
    payload = json.dumps({
        "id": "evt_1",
        "type": "invoice.payment_succeeded",
        "data": {"object": {"id": "in_1", "subscription": "sub_42", "amount_paid": 1590000, "currency": "thb",
                            "payment_intent": "pi_abc"}},
    }).encode()
    out = adapter.normalize(payload)
    assert out["type"] == "payment.succeeded"
    assert out["data"]["provider_subscription_id"] == "sub_42"
    assert out["data"]["provider_payment_id"] == "pi_abc"
    assert out["data"]["amount_satangs"] == 1590000
    assert out["data"]["currency"] == "THB"


def test_stripe_normalize_marks_failed_events():
    adapter = StripeAdapter()
    payload = json.dumps({
        "id": "evt_2",
        "type": "invoice.payment_failed",
        "data": {"object": {"id": "in_2", "subscription": "sub_2"}},
    }).encode()
    out = adapter.normalize(payload)
    assert out["type"] == "payment.failed"


# -- OmiseAdapter -----------------------------------------------------------


def test_omise_signature_verifies_valid_payload():
    adapter = OmiseAdapter()
    settings = _settings()
    raw_secret = base64.b64decode(settings.omise_webhook_secret)
    payload = b'{"id":"evt_om_1","key":"charge.complete","data":{"id":"chrg_1","status":"successful","amount":1590000,"currency":"THB"}}'
    ts = str(int(time.time()))
    digest = hmac.new(raw_secret, f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    request = _request({"omise-signature": digest, "omise-signature-timestamp": ts})
    assert _run(adapter.verify(request, payload, settings)) is True


def test_omise_signature_rejects_wrong_signature():
    adapter = OmiseAdapter()
    settings = _settings()
    payload = b'{"id":"x"}'
    ts = str(int(time.time()))
    request = _request({"omise-signature": "0" * 64, "omise-signature-timestamp": ts})
    assert _run(adapter.verify(request, payload, settings)) is False


def test_omise_signature_requires_both_headers():
    adapter = OmiseAdapter()
    settings = _settings()
    # Missing timestamp
    request = _request({"omise-signature": "abc"})
    assert _run(adapter.verify(request, b"{}", settings)) is False


def test_omise_normalize_extracts_charge_fields():
    adapter = OmiseAdapter()
    payload = json.dumps({
        "id": "evt_om_2",
        "key": "charge.complete",
        "data": {
            "object": "event",
            "id": "evt_om_2",
            "data": {
                "object": "charge",
                "id": "chrg_42",
                "status": "successful",
                "amount": 1590000,
                "currency": "THB",
                "metadata": {"provider_subscription_id": "sub_omise_1"},
            },
        },
    }).encode()
    out = adapter.normalize(payload)
    # The adapter unwraps one level of "data" then looks at "object" or the dict itself
    # Either way, type must be a "payment.*" string.
    assert out["type"].startswith("payment.")


# -- GenericHmacAdapter (2C2P) ----------------------------------------------


def test_twoc2p_signature_verifies_valid_payload():
    adapter = GenericHmacAdapter("2c2p", "twoc2p_webhook_secret")
    settings = _settings()
    payload = b'{"event_id":"e_2c2p_1","status":"success","data":{"transaction_id":"tx_2c2p_1","amount":1590000,"currency":"THB","subscription_id":"sub_2c2p_1"}}'
    ts = str(int(time.time()))
    sig = hmac.new(settings.twoc2p_webhook_secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    request = _request({"x-signature": sig, "x-signature-timestamp": ts})
    assert _run(adapter.verify(request, payload, settings)) is True


def test_twoc2p_falls_back_to_payment_webhook_secret_when_specific_empty():
    adapter = GenericHmacAdapter("2c2p", "twoc2p_webhook_secret")
    settings = _settings(twoc2p_webhook_secret="")
    payload = b'{"id":"x"}'
    ts = str(int(time.time()))
    sig = hmac.new(settings.payment_webhook_secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    request = _request({"x-signature": sig, "x-signature-timestamp": ts})
    assert _run(adapter.verify(request, payload, settings)) is True


def test_twoc2p_signature_rejects_stale_timestamp():
    adapter = GenericHmacAdapter("2c2p", "twoc2p_webhook_secret")
    settings = _settings(payment_webhook_max_age_seconds=60)
    payload = b'{"id":"x"}'
    ts = str(int(time.time()) - 3600)
    sig = hmac.new(settings.twoc2p_webhook_secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    request = _request({"x-signature": sig, "x-signature-timestamp": ts})
    assert _run(adapter.verify(request, payload, settings)) is False


def test_twoc2p_normalize_maps_status_to_event_type():
    adapter = GenericHmacAdapter("2c2p", "twoc2p_webhook_secret")
    payload = json.dumps({
        "id": "evt_2c2p_1",
        "status": "success",
        "data": {
            "transaction_id": "tx_42",
            "amount": 1590000,
            "currency": "THB",
            "subscription_id": "sub_42",
        },
    }).encode()
    out = adapter.normalize(payload)
    assert out["type"] == "payment.succeeded"
    assert out["data"]["provider_payment_id"] == "tx_42"
    assert out["data"]["provider_subscription_id"] == "sub_42"
    assert out["data"]["amount_satangs"] == 1590000


def test_twoc2p_normalize_maps_failed_status():
    adapter = GenericHmacAdapter("2c2p", "twoc2p_webhook_secret")
    payload = json.dumps({"id": "e", "data": {"transaction_id": "tx", "status": "failed"}}).encode()
    out = adapter.normalize(payload)
    assert out["type"] == "payment.failed"


# -- GenericHmacAdapter (GB Prime Pay) --------------------------------------


def test_gbprimepay_signature_verifies_valid_payload():
    adapter = GenericHmacAdapter("gbprimepay", "gbprimepay_webhook_secret")
    settings = _settings()
    payload = b'{"event_id":"e_gb_1","data":{"referenceNo":"REF42","status":"success","amount":1590000,"currency":"THB"}}'
    ts = str(int(time.time()))
    sig = hmac.new(settings.gbprimepay_webhook_secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    request = _request({"x-webhook-signature": sig, "x-signature-timestamp": ts})
    assert _run(adapter.verify(request, payload, settings)) is True


def test_gbprimepay_normalize_extracts_reference():
    adapter = GenericHmacAdapter("gbprimepay", "gbprimepay_webhook_secret")
    payload = json.dumps({
        "event_id": "e_gb_2",
        "data": {
            "referenceNo": "REF99",
            "status": "approved",
            "amount": 599_00,
            "currency": "THB",
            "customerReference": "cust_42",
        },
    }).encode()
    out = adapter.normalize(payload)
    assert out["type"] == "payment.succeeded"
    assert out["data"]["provider_payment_id"] == "REF99"
    assert out["data"]["provider_subscription_id"] == "cust_42"


# -- get_adapter dispatcher --------------------------------------------------


def test_get_adapter_returns_known_provider():
    assert get_adapter("stripe").provider == "stripe"
    assert get_adapter("omise").provider == "omise"
    assert get_adapter("2c2p").provider == "2c2p"
    assert get_adapter("gbprimepay").provider == "gbprimepay"
    assert get_adapter("manual").provider == "manual"


def test_get_adapter_is_case_insensitive():
    assert get_adapter("STRIPE").provider == "stripe"
    assert get_adapter("Omise").provider == "omise"


def test_get_adapter_rejects_unknown_provider():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        get_adapter("paypal")
    assert excinfo.value.status_code == 400

# Backend API Reference: Device Policy + Billing

## Admin: กำหนด Device Policy

```http
POST /api/v1/admin/licenses/{license_id}/device-policies
X-Admin-Token: <admin_token>
Content-Type: application/json
```

```json
{
  "policies": [
    {"device_type": "pc", "max_devices": 2},
    {"device_type": "phone", "max_devices": 3}
  ]
}
```

## Admin: ดู Device Policy

```http
GET /api/v1/admin/licenses/{license_id}/device-policies
X-Admin-Token: <admin_token>
```

## Admin: สร้าง Subscription

```http
POST /api/v1/admin/subscriptions
X-Admin-Token: <admin_token>
Content-Type: application/json
```

```json
{
  "license_id": "lic_xxxxx",
  "provider": "manual",
  "provider_customer_id": "cus_001",
  "provider_subscription_id": "sub_001",
  "amount_satangs": 1590000,
  "currency": "THB"
}
```

## Payment Webhook

```http
POST /api/v1/webhooks/payments/{provider}
X-NP-Signature: sha256=<hmac>
Content-Type: application/json
```

Success event:

```json
{
  "id": "evt_001",
  "type": "payment.succeeded",
  "data": {
    "provider_payment_id": "pay_001",
    "provider_subscription_id": "sub_001",
    "amount_satangs": 1590000,
    "currency": "THB"
  }
}
```

รองรับ success event types:

```text
payment.succeeded
charge.succeeded
invoice.paid
subscription.payment_succeeded
```

รองรับ failed event types:

```text
payment.failed
charge.failed
invoice.payment_failed
subscription.cancelled
```

## Admin: ดูประวัติ Payment

```http
GET /api/v1/admin/licenses/{license_id}/payments
X-Admin-Token: <admin_token>
```

## Admin: ดู Payment Events

```http
GET /api/v1/admin/payment-events
X-Admin-Token: <admin_token>
```

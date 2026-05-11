# คู่มือระบบ Device Policy และ Auto Billing

## Device Policy

หลังบ้านสามารถกำหนดจำนวนอุปกรณ์ต่อ License ได้อิสระ เช่น:

```json
{
  "policies": [
    {"device_type": "pc", "max_devices": 1},
    {"device_type": "phone", "max_devices": 1},
    {"device_type": "tablet", "max_devices": 2}
  ]
}
```

เมื่อ Client activate license ระบบจะตรวจ:

1. License key ถูกต้องหรือไม่
2. License active และยังไม่หมดอายุหรือไม่
3. `device_type` นี้ถูกอนุญาตใน `device_policies` หรือไม่
4. จำนวนเครื่องที่ bind อยู่เกิน `max_devices` หรือไม่
5. ถ้าเต็ม ต้องให้ Admin release เครื่องเดิมก่อน

## Auto Billing

เมื่อชำระเงินสำเร็จ Payment Gateway ส่ง webhook:

```http
POST /api/v1/webhooks/payments/{provider}
X-NP-Signature: sha256=<hmac-sha256>
```

ตัวอย่าง payload แบบ normalized:

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

Backend จะต่ออายุ License ให้อัตโนมัติ โดยอิงจาก `provider_subscription_id` ที่เคยผูกกับ License ไว้ในตาราง `subscriptions`

## คำสั่งสร้าง Subscription

```bash
python scripts/admin_create_subscription.py ^
  --base-url http://127.0.0.1:8088 ^
  --admin-token dev_admin_token_please_change_123456 ^
  --license-id lic_xxxxx ^
  --provider manual ^
  --provider-subscription-id sub_customer_001 ^
  --amount-satangs 1590000
```

## คำสั่งจำลอง Webhook

```bash
python scripts/simulate_payment_webhook.py ^
  --base-url http://127.0.0.1:8088 ^
  --secret dev_payment_webhook_secret_please_change_123456 ^
  --provider manual ^
  --provider-payment-id pay_test_001 ^
  --provider-subscription-id sub_customer_001 ^
  --amount-satangs 1590000
```

## Security Notes

- Webhook ต้องมี signature เสมอ
- ห้ามต่ออายุจากข้อมูลที่ Client ส่งมาเองโดยไม่มี Payment Gateway ยืนยัน
- ใช้ idempotency จาก `external_event_id`
- เก็บ payment payload hash เพื่อ audit โดยไม่ต้องเก็บข้อมูลบัตร/ข้อมูลละเอียดเกินจำเป็น

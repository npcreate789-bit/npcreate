# รายงานปรับปรุงระบบ Device Policy + Auto Billing License

## เป้าหมายการปรับปรุง

ปรับระบบ License ให้รองรับการใช้งานระดับ Production มากขึ้น โดยเพิ่ม 2 แกนหลัก:

1. ระบบผูกเครื่องแบบกำหนดได้อิสระจากหลังบ้าน
2. ระบบต่ออายุ License รายเดือนอัตโนมัติเมื่อชำระเงินสำเร็จ

การปรับนี้ออกแบบให้ Logic สำคัญอยู่ฝั่ง Backend ไม่ใช่อยู่ในเครื่องลูกค้า เพื่อป้องกันการแก้ไขโปรแกรมฝั่ง Client แล้วหลบระบบ License

---

## 1. ระบบผูกเครื่องแบบกำหนดได้อิสระ

### ปัญหาเดิม

ระบบเดิมกำหนดไว้ค่อนข้างตายตัว:

```text
1 License = max_pc_devices + max_phone_devices
```

และในตาราง `devices` มีข้อจำกัด device type เป็นเพียง `pc` หรือ `phone` เท่านั้น ทำให้ในอนาคตปรับยาก เช่น:

- ลูกค้า A ใช้ได้ 1 คอม + 1 มือถือ
- ลูกค้า B ใช้ได้ 3 คอม + 0 มือถือ
- ลูกค้า C ใช้ได้ 1 คอม + 2 มือถือ
- ลูกค้า D ใช้ได้ 1 คอม + 1 แท็บเล็ต
- เพิ่ม device type ใหม่ เช่น `tablet`, `pos`, `server`, `android_box`

### สิ่งที่แก้ไข

เพิ่มตาราง `device_policies`

```text
device_policies
├── policy_id
├── license_id
├── device_type
├── max_devices
├── binding_mode
├── fingerprint_required
├── metadata_json
├── created_at
└── updated_at
```

ตัวอย่าง Policy:

```json
[
  {"device_type": "pc", "max_devices": 1},
  {"device_type": "phone", "max_devices": 1},
  {"device_type": "tablet", "max_devices": 2}
]
```

หลังบ้านสามารถปรับได้ต่อ License โดยไม่ต้องแก้ Source Code

### API ที่เพิ่ม

```http
GET /api/v1/admin/licenses/{license_id}/device-policies
POST /api/v1/admin/licenses/{license_id}/device-policies
```

### ตัวอย่าง Payload

```json
{
  "policies": [
    {
      "device_type": "pc",
      "max_devices": 2,
      "binding_mode": "admin_release_only",
      "fingerprint_required": true
    },
    {
      "device_type": "phone",
      "max_devices": 3,
      "binding_mode": "admin_release_only",
      "fingerprint_required": true
    }
  ]
}
```

### ความปลอดภัยที่เพิ่ม

- Device Type ถูก validate ด้วย regex ป้องกัน input แปลกปลอม
- จำกัดจำนวนอุปกรณ์สูงสุดต่อ device type ไม่เกิน 200
- ถ้า License ไม่มี Policy ของ device type นั้น จะลงทะเบียนไม่ได้
- ถ้าลงทะเบียนครบจำนวนแล้ว ต้องให้ Admin ปลดเครื่องเดิมก่อน
- `device_fingerprint` ยังถูกเก็บเป็น hash ฝั่ง client/backend ไม่ควรเก็บ serial ดิบแบบไม่จำเป็น

---

## 2. ระบบ License รายเดือนแบบต่ออายุอัตโนมัติ

### เป้าหมาย

เมื่อระบบชำระเงินแจ้งว่า Payment สำเร็จ Backend จะ:

1. ตรวจลายเซ็น Webhook
2. ตรวจว่า Event นี้เคยประมวลผลแล้วหรือยัง
3. ผูก Payment กับ Subscription / License
4. บันทึก Payment
5. ต่ออายุ License ให้อัตโนมัติ
6. บันทึก Audit Log

### ตารางที่เพิ่ม

```text
subscriptions
├── subscription_id
├── license_id
├── provider
├── provider_customer_id
├── provider_subscription_id
├── status
├── billing_cycle
├── amount_satangs
├── currency
├── next_renewal_at
├── last_payment_at
├── created_at
└── updated_at

payments
├── payment_id
├── license_id
├── subscription_id
├── provider
├── provider_payment_id
├── provider_subscription_id
├── status
├── amount_satangs
├── currency
├── paid_at
├── raw_payload_hash
└── created_at

payment_events
├── event_id
├── provider
├── external_event_id
├── event_type
├── signature_valid
├── payload_hash
├── processing_status
├── error
├── received_at
└── processed_at

audit_logs
├── audit_id
├── actor_type
├── actor_id
├── action
├── target_type
├── target_id
├── ip_address
├── metadata_json
└── created_at
```

### API ที่เพิ่ม

```http
POST /api/v1/admin/subscriptions
GET  /api/v1/admin/licenses/{license_id}/subscriptions
GET  /api/v1/admin/licenses/{license_id}/payments
GET  /api/v1/admin/payment-events
POST /api/v1/webhooks/payments/{provider}
```

### Flow ต่ออายุอัตโนมัติ

```text
Payment Gateway
→ ส่ง Webhook มาที่ Backend
→ Backend ตรวจ X-NP-Signature
→ ตรวจ external_event_id ว่าซ้ำไหม
→ หา subscription จาก provider_subscription_id
→ หา license_id จาก subscription
→ บันทึก payment
→ ต่ออายุ expires_at + 31 วันจากวันหมดอายุเดิม หรือจากวันนี้ แล้วแต่วันไหนมากกว่า
→ อัปเดต subscription.last_payment_at / next_renewal_at
→ บันทึก audit log
```

---

## 3. จุดป้องกันช่องโหว่ที่เพิ่ม

| ความเสี่ยง | การป้องกันที่เพิ่ม |
|---|---|
| ลูกค้าแก้จำนวนเครื่องเอง | จำนวนเครื่องอยู่ใน Backend `device_policies` |
| ผูกอุปกรณ์ชนิดใหม่ไม่ได้ | รองรับ device type แบบ dynamic |
| Webhook ปลอมมาต่ออายุฟรี | ตรวจ HMAC-SHA256 signature |
| Webhook ส่งซ้ำแล้วต่ออายุซ้ำ | ใช้ `UNIQUE(provider, external_event_id)` |
| Payment ID ซ้ำ | ใช้ `UNIQUE(provider, provider_payment_id)` |
| แก้ข้อมูลจาก Client เพื่อระบุ license_id มั่ว | ให้ priority กับ mapping จาก `provider_subscription_id` ใน Backend |
| ตรวจสอบย้อนหลังไม่ได้ | เพิ่ม `audit_logs`, `payments`, `payment_events` |
| payload ใหญ่ผิดปกติ | จำกัด webhook payload ไม่เกิน 512 KB |
| secret อ่อนใน production | startup fail ถ้าใช้ `CHANGE_ME` หรือ secret สั้น |

---

## 4. ไฟล์สำคัญที่เพิ่ม/แก้

```text
src/npcreate_backend/db.py
src/npcreate_backend/models.py
src/npcreate_backend/security.py
src/npcreate_backend/settings.py
src/npcreate_backend/billing.py
src/npcreate_backend/routes_admin.py
src/npcreate_backend/routes_public.py
scripts/admin_create_subscription.py
scripts/simulate_payment_webhook.py
docs/AUTO_BILLING_DEVICE_POLICY_TH.md
docs/BACKEND_API_BILLING_REFERENCE_TH.md
tests/unit/test_backend_billing.py
```

---

## 5. คำแนะนำ Production เพิ่มเติม

ก่อนใช้งานจริง ควรทำเพิ่ม:

1. ใช้ PostgreSQL แทน SQLite สำหรับ Production Backend ที่มีผู้ใช้หลายราย
2. ใช้ provider-specific webhook verification ตามเอกสารของ Payment Gateway จริง
3. บังคับ HTTPS เท่านั้นสำหรับ Backend และ Webhook
4. เก็บ secret ใน Secret Manager ไม่เก็บในไฟล์ `.env` บนเครื่อง production แบบ plain text
5. เปิด rate limit สำหรับ `/licenses/activate`, `/licenses/heartbeat`, `/webhooks/*`
6. ทำ Admin Panel ที่ใช้ MFA ไม่ใช่แค่ `X-Admin-Token`
7. เพิ่ม Job รายวันเพื่อตรวจ License หมดอายุ / payment failed / grace period
8. แยก role admin เช่น owner, support, finance, developer
9. เก็บ Audit Log แบบ append-only หรือส่งเข้า log server ภายนอก

---

## 6. ผลทดสอบ

```text
python -m compileall -q src scripts tests
PYTHONPATH=src pytest -q

13 tests passed
```

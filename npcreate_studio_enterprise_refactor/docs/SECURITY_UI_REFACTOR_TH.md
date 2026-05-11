# รายงานตรวจสอบโครงสร้าง + Security Hardening + UX/UI Refactor

เวอร์ชันชุดนี้: `2.3.0`

## ขอบเขตการตรวจ

ตรวจจากโครงสร้าง Source Code ชุดล่าสุด `Auto Billing + Device Policy` แบบ Static Audit และปรับปรุงต่อโดยไม่รัน executable/vendor tools ใด ๆ เช่น `.exe`, `.apk`, `.jar`, ADB, FFmpeg, scrcpy หรือ MediaMTX

## สรุปจุดบกพร่อง / ช่องโหว่ที่พบ

| จุดที่พบ | ความเสี่ยง | การแก้ไขในชุดนี้ |
|---|---|---|
| Activation endpoint ยังเสี่ยงถูกยิงซ้ำเพื่อเดา License | Brute force / credential stuffing | เพิ่ม in-process rate limit ต่อ IP สำหรับ `/licenses/activate` |
| Admin token เดิมเทียบด้วย `!=` ตรง ๆ | Timing leak ระดับเล็ก | เปลี่ยนเป็น `hmac.compare_digest` ผ่าน `constant_time_equal()` |
| Device fingerprint ถูกใช้ตรงเกินไป | เสี่ยงเก็บ serial/device ID แบบระบุตัวตนได้ | เพิ่ม `hash_device_fingerprint()` ฝั่ง Backend ด้วย HMAC + pepper ก่อนบันทึก DB |
| Device metadata ไม่จำกัดขนาดชัดเจน | Payload ใหญ่ / log pollution / DB โตผิดปกติ | เพิ่ม `sanitize_metadata()` และ validator ใน Pydantic models |
| Payment webhook เดิม fallback รับ `license_id` จาก payload ได้ | ถ้า webhook secret หลุด อาจต่ออายุ license ผิดตัวได้ง่าย | บังคับ map ผ่าน `provider_subscription_id` ที่มีอยู่ใน DB เป็นค่าเริ่มต้น |
| Webhook signature ยังไม่มี timestamp replay guard | อาจนำ payload เก่ากลับมายิงซ้ำในบางกรณี | เพิ่ม timestamp signature mode: `HMAC(secret, timestamp.payload)` และ production require timestamp |
| Payment amount/currency ไม่บังคับเทียบ subscription | ชำระยอดผิดแต่ต่ออายุได้ | เพิ่มตรวจ `amount_satangs` และ `currency` ให้ตรงกับ subscription |
| Admin ยังไม่มี flow อนุมัติ/ปฏิเสธคำขอปลดเครื่อง | Support ทำงานยาก และตรวจสอบย้อนหลังยาก | เพิ่ม API: list/approve/reject release requests + audit logs |
| UI เดิมเป็นหน้า placeholder | ลูกค้าใช้งานจริงสับสน | ปรับเป็น CustomTkinter shell: sidebar, dashboard, license, devices, update, news, settings |
| UI logic มีโอกาสปนกับ business logic | ดูแลยาก | แยก UI pages/components ออกจาก services/infrastructure |

## Backend ที่ปรับเพิ่ม

### Security

- `npcreate_backend/security.py`
  - เพิ่ม `constant_time_equal()`
  - เพิ่ม `hash_device_fingerprint()`
  - เพิ่ม `sanitize_metadata()`
  - เพิ่ม timestamp-aware `verify_webhook_signature()`

- `npcreate_backend/auth.py`
  - Admin/API token ใช้ constant-time compare
  - เพิ่ม `rate_limit_activation()`
  - รองรับ trusted proxy header สำหรับ production reverse proxy

### License / Device Binding

- `npcreate_backend/routes_public.py`
  - Activation เก็บเฉพาะ HMAC ของ fingerprint
  - Activation endpoint ถูก rate limit
  - Metadata ถูก sanitize ก่อนเก็บ

- `npcreate_backend/routes_admin.py`
  - เพิ่มดูรายละเอียด License พร้อม policies/counts
  - เพิ่มรายการคำขอปลดเครื่อง
  - เพิ่มอนุมัติคำขอปลดเครื่อง
  - เพิ่มปฏิเสธคำขอปลดเครื่อง
  - เพิ่ม audit log endpoint

### Auto Billing

- `npcreate_backend/billing.py`
  - Payment success ต้อง map ผ่าน known subscription เป็นค่าเริ่มต้น
  - Reject ถ้า amount/currency ไม่ตรงกับ subscription
  - Reject duplicate event/payment อย่าง idempotent
  - บันทึก audit log ทุก action สำคัญ

## UX/UI ที่ปรับเพิ่ม

### หน้าใหม่

| หน้า | จุดประสงค์ |
|---|---|
| Dashboard | เห็นภาพรวม License / Device / Update / Security ในหน้าเดียว |
| License | กรอก Key, Activate เครื่อง, ขอปลดเครื่องเดิม |
| Devices | อธิบายการผูกเครื่อง และ policy ที่ Admin กำหนดได้ |
| Updates | ตรวจเวอร์ชันและแพทช์แบบ signed update |
| News | ข่าวสารจากทีม NP Create |
| Settings | ตรวจ path, server URL, dashboard host, tool manifest |

### UX ที่เน้น

- Sidebar ชัดเจน ไม่ต้องจำเมนู
- ใช้ status pill เช่น `ON`, `ปลอดภัย`, `ยังไม่ Activate`
- Dashboard แสดง action ต่อไปที่ควรทำ
- แยกข้อความอธิบายสำหรับลูกค้า ลดความสับสนเรื่อง “ผูกเครื่อง”
- สีหลักดำ/แดงเข้ากับ NP Create และดูเป็นระบบ Production

## Production Checklist ที่ยังควรทำก่อนใช้งานจริง

1. เปลี่ยน SQLite เป็น PostgreSQL สำหรับ Backend จริง
2. วาง Backend หลัง HTTPS + Reverse Proxy + WAF/Rate Limit
3. Admin panel ควรใช้ Login + MFA + Role-based access ไม่ใช้ token เดียวระยะยาว
4. Webhook แต่ละ Payment Gateway ต้องใช้ signature spec ทางการของผู้ให้บริการ
5. เก็บ secret ใน Secret Manager ไม่เก็บใน `.env` บนเครื่อง production
6. เพิ่ม background job สำหรับตรวจ subscription ค้างชำระ/หมด grace period
7. เพิ่ม signed installer และ code signing certificate สำหรับ Windows
8. เพิ่ม telemetry แบบ privacy-preserving เพื่อดู crash/error โดยไม่เก็บข้อมูลส่วนตัวเกินจำเป็น
9. เพิ่ม E2E test สำหรับ Activate → Heartbeat → Payment → Renew → Release device
10. เพิ่ม Admin UI บน Web สำหรับดู license/subscription/release requests แทนเรียก API ตรง

## ผลทดสอบ

```bash
python -m compileall -q src scripts tests
PYTHONPATH=src pytest -q
```

ผลลัพธ์:

```text
17 tests passed
```

## ไฟล์สำคัญที่เพิ่ม/แก้

```text
src/npcreate_backend/security.py
src/npcreate_backend/auth.py
src/npcreate_backend/billing.py
src/npcreate_backend/models.py
src/npcreate_backend/routes_public.py
src/npcreate_backend/routes_admin.py
src/npcreate_backend/settings.py
src/npcreate_studio/ui/main_window.py
src/npcreate_studio/ui/theme.py
src/npcreate_studio/ui/components/__init__.py
src/npcreate_studio/ui/pages/dashboard_page.py
src/npcreate_studio/ui/pages/license_page.py
src/npcreate_studio/ui/pages/devices_page.py
src/npcreate_studio/ui/pages/updates_page.py
src/npcreate_studio/ui/pages/news_page.py
src/npcreate_studio/ui/pages/settings_page.py
tests/unit/test_backend_hardening.py
```

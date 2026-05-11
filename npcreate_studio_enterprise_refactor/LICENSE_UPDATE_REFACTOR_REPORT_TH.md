# รายงานวิเคราะห์และปรับปรุง: Update Patch + Backend License รายเดือน

## สิ่งที่เพิ่มให้แล้ว

เพิ่มโครงสร้างระบบใหม่จาก `npcreate_studio_secure_refactor` เป็นเวอร์ชัน `2.1.0` โดยเพิ่ม 2 ส่วนหลัก

1. **Client-side services** สำหรับโปรแกรมลูกค้า
2. **Backend API** สำหรับ Admin และระบบ License

## Module ใหม่ฝั่ง Client

| ไฟล์ | หน้าที่ |
|---|---|
| `services/device_identity.py` | สร้าง Fingerprint ของคอมและมือถือแบบ hash ไม่ส่ง serial ดิบไปหลังบ้าน |
| `services/license_client.py` | Activate license, heartbeat, ดึงข่าวสาร, ขอปลดอุปกรณ์ |
| `services/update_client.py` | เช็กเวอร์ชันใหม่, ตรวจ signature, ดาวน์โหลด patch, ตรวจ SHA256 |
| `services/notification_service.py` | จัดการข่าวสารที่อ่านแล้ว |
| `services/client_state_service.py` | เก็บ state เบื้องต้นของ client |
| `domain/licenses.py` | เพิ่ม DeviceType, LicenseStatus, ActivationResult, NewsItem, UpdateInfo |

## Module ใหม่ฝั่ง Backend

| ไฟล์ | หน้าที่ |
|---|---|
| `npcreate_backend/app.py` | FastAPI app factory |
| `npcreate_backend/db.py` | SQLite schema + migration |
| `npcreate_backend/models.py` | Request/Response schema |
| `npcreate_backend/security.py` | สร้าง key, hash key, token, sign update manifest |
| `npcreate_backend/auth.py` | Admin auth + activation bearer token |
| `npcreate_backend/routes_public.py` | API สำหรับ Client |
| `npcreate_backend/routes_admin.py` | API สำหรับ Admin |
| `npcreate_backend/settings.py` | Environment settings ฝั่ง backend |

## ระบบ License ที่ออกแบบให้

### 1 License ใช้ได้เฉพาะเครื่องที่ผูกไว้

ค่าเริ่มต้นที่แนะนำ:

- คอม: 1 เครื่อง
- โทรศัพท์: 1 เครื่อง

ถ้าลูกค้านำ Key เดิมไปใช้เครื่องใหม่ ระบบจะตอบกลับว่า `device limit reached` และต้องให้ Admin ปลดเครื่องเดิมก่อน

### การต่ออายุรายเดือน

Admin สามารถเรียก API:

```text
POST /api/v1/admin/licenses/{license_id}/renew
```

ระบบจะขยายวันหมดอายุจากวันหมดอายุเดิม ไม่ใช่จากวันที่กดต่ออายุ ถ้ายังไม่หมดอายุ

## ระบบ Update Patch

ระบบใช้ signed manifest:

```json
{
  "version": "2.1.1",
  "channel": "stable",
  "mandatory": false,
  "download_url": "https://.../patch.zip",
  "sha256": "...",
  "signature": "..."
}
```

Client จะตรวจ:

1. Signature ด้วย Ed25519 public key
2. SHA256 ของไฟล์ patch
3. แตก ZIP ด้วย `safe_extract_zip` เพื่อกัน path traversal

## ช่องโหว่ที่ปิด/ลดความเสี่ยงแล้ว

| ความเสี่ยง | วิธีป้องกันที่เพิ่ม |
|---|---|
| Key ถูกเดา | ใช้ `secrets` สร้าง key แบบสุ่ม |
| Key หลุดจากฐานข้อมูล | Backend เก็บเฉพาะ HMAC-SHA256 + pepper ไม่เก็บ key ดิบ |
| ใช้ Key หลายเครื่อง | ผูก fingerprint ตาม license และ device type |
| ปลอม update | ใช้ signature + SHA256 |
| zip slip ตอน update | ใช้ safe zip extraction |
| Admin API ถูกเรียกมั่ว | ใช้ `X-Admin-Token` และบังคับ secret แข็งแรงใน production |
| Client token ถูกแก้ไข | ใช้ HMAC signed activation token |
| ใช้ license หลังถูก revoke/suspend | Client ต้อง heartbeat กับ server เป็นระยะ |

## สิ่งที่ยังควรทำเพิ่มก่อน Production จริง

1. เพิ่ม Admin Web UI พร้อม login, RBAC และ audit log
2. เพิ่ม rate limit ต่อ IP / license key / device fingerprint
3. เพิ่ม payment webhook ต่ออายุอัตโนมัติ
4. เพิ่ม email/LINE แจ้งเตือนก่อนหมดอายุ
5. เพิ่ม backup database อัตโนมัติ
6. เพิ่ม HTTPS/TLS เท่านั้นใน production
7. เพิ่ม Code Signing ให้ตัว installer/exe
8. เพิ่ม remote kill-switch สำหรับ license ที่ผิดเงื่อนไข
9. เพิ่มระบบ restore license กรณีลูกค้าลง Windows ใหม่ แต่ยังเป็นเครื่องเดิม
10. เพิ่ม Dashboard สำหรับดูจำนวนเครื่องที่ activate และประวัติการปลดเครื่อง

## คำสั่ง Run Backend แบบ Local Dev

```bash
cd npcreate_studio_license_update_refactor
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
set NPCREATE_BACKEND_ENV=development
set NPCREATE_BACKEND_ADMIN_TOKEN=dev_admin_token_please_change_123456
set NPCREATE_BACKEND_APP_API_KEY=dev_app_api_key_please_change_123456
set NPCREATE_BACKEND_KEY_PEPPER=dev_key_pepper_please_change_123456
npcreate-backend
```

## คำสั่งสร้าง License Key

```bash
python scripts/admin_create_license.py ^
  --base-url http://127.0.0.1:8088 ^
  --admin-token dev_admin_token_please_change_123456 ^
  --customer-name "Customer A" ^
  --months 1 ^
  --max-pc 1 ^
  --max-phone 1
```

## คำสั่งประกาศ Update Patch

```bash
python scripts/publish_update_manifest.py ^
  --base-url http://127.0.0.1:8088 ^
  --admin-token dev_admin_token_please_change_123456 ^
  --version 2.1.1 ^
  --download-url https://your-domain.com/releases/patch-2.1.1.zip ^
  --file dist/patch-2.1.1.zip ^
  --channel stable ^
  --release-notes "แก้บั๊กและปรับปรุงระบบ"
```

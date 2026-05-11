# NP Create Studio Enterprise Production Upgrade 2.4.0

เอกสารนี้สรุปส่วนที่เพิ่มตามรายการที่ต้องการทั้งหมด

## 1) Admin Web Dashboard จริง
เพิ่มหน้า `/admin` สำหรับจัดการภาพรวม, License, Payment, Device, Logs/Error และ Settings โดยใช้ FastAPI + Jinja2 Templates

## 2) PostgreSQL
เพิ่ม `NPCREATE_BACKEND_DATABASE_URL=postgresql://user:password@host:5432/dbname` ระบบจะใช้ PostgreSQL แทน SQLite ทันที โดยมี adapter แปลง placeholder เดิมเพื่อให้ refactor ต่อได้อย่างปลอดภัย

## 3) Admin Login + MFA
เพิ่ม `admin_users`, `admin_sessions` และ TOTP MFA ใช้ Argon2 สำหรับ hash password และ cookie session แบบ HttpOnly/SameSite

สร้าง admin คนแรก:

```bash
python scripts/admin_create_user.py --email admin@example.com --password "StrongPasswordHere"
```

## 4) Payment Gateway จริง
เพิ่ม adapter pattern สำหรับ:
- Stripe
- Omise
- 2C2P
- GB Prime Pay
- Manual/Internal

เส้นทาง webhook:

```text
POST /api/v1/public/webhooks/payments/{provider}
```

ค่าที่ต้องตั้ง:

```text
NPCREATE_BACKEND_STRIPE_WEBHOOK_SECRET=
NPCREATE_BACKEND_OMISE_WEBHOOK_SECRET=
NPCREATE_BACKEND_TWOC2P_WEBHOOK_SECRET=
NPCREATE_BACKEND_GBPRIMEPAY_WEBHOOK_SECRET=
```

## 5) Background Job
เพิ่ม job ตรวจ subscription ที่เลยวันชำระ:
- `active` → `past_due`
- เกิน grace period → `suspended`

สั่งรัน manual ได้:

```bash
python scripts/run_billing_maintenance.py
```

## 6) Log Viewer / Error Report
Client UI เพิ่มหน้า `Log / Error Report` และ backend เพิ่มตาราง `error_reports` พร้อม endpoint:

```text
POST /api/v1/public/error-reports
```

## 7) Windows Installer + Code Signing
เพิ่ม:

```text
scripts/build_windows_installer.ps1
scripts/sign_windows_artifacts.ps1
installer/NPCreateStudio.iss
```

Production ต้องใช้ OV/EV Code Signing Certificate และตั้งค่า:

```powershell
$env:NPCREATE_SIGN_CERT_SHA1="YOUR_CERT_THUMBPRINT"
```

## 8) Toast แจ้งเตือนใน UI
เพิ่ม `ToastManager` สำหรับแจ้งสถานะสำเร็จ/เตือน/ผิดพลาด เช่น Activate สำเร็จ, License หมดอายุ, Update พร้อมติดตั้ง

## Security Checklist รอบนี้

- ปิด legacy admin token ใน production
- ใช้ HTTPS ทุก endpoint
- ตั้ง SameSite/HttpOnly/Secure cookie
- ใช้ PostgreSQL managed database พร้อม backup
- แยก webhook secret ต่อ provider
- เปิด WAF/rate limit หน้า login และ activation
- เปิด log monitoring สำหรับ audit_logs + error_reports
- บังคับ code signing ก่อนปล่อยไฟล์ให้ลูกค้า

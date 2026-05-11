# รายงานปรับปรุง Enterprise Security + UX/UI 2.4.0

## รายการที่เพิ่มแล้ว

| รายการ | สถานะ | ไฟล์หลัก |
|---|---|---|
| Admin Web Dashboard | เพิ่มแล้ว | `routes_dashboard.py`, `templates/admin/*` |
| PostgreSQL Backend | เพิ่มแล้ว | `db.py`, `settings.py` |
| Admin Login + MFA | เพิ่มแล้ว | `routes_auth.py`, `admin_security.py` |
| Payment Gateway Adapters | เพิ่มแล้ว | `payment_providers.py` |
| Background Billing Job | เพิ่มแล้ว | `jobs.py`, `run_billing_maintenance.py` |
| Log Viewer / Error Report | เพิ่มแล้ว | `logs_page.py`, `error_reporter.py`, `error_reports` table |
| Windows Installer + Code Signing | เพิ่มแล้ว | `scripts/*.ps1`, `installer/NPCreateStudio.iss` |
| Toast Notification | เพิ่มแล้ว | `ui/components/toast.py` |

## จุดที่ยังต้องเชื่อมจริงก่อน Production

1. ใส่ secret จริงของแต่ละ Payment Gateway
2. ตรวจ field mapping กับ merchant account จริงของ 2C2P / GB Prime Pay เพราะแต่ละ merchant อาจตั้ง callback payload ต่างกัน
3. ใช้ PostgreSQL จริงและรัน migration ใน staging ก่อน production
4. ใช้ HTTPS + reverse proxy + WAF
5. ทำ Admin MFA recovery process เช่น backup code หรือ admin คู่สำรอง
6. ซื้อและติดตั้ง Code Signing Certificate จริง

## โครงสร้างความปลอดภัยใหม่

- Password ใช้ Argon2
- MFA ใช้ TOTP 6 หลัก
- Session ใช้ random token + SHA256 hash ใน DB
- Payment webhook แยก adapter ตาม provider
- Billing job suspend license อัตโนมัติเมื่อเกิน grace period
- Client ส่ง error report แบบไม่แนบ secret
- Installer มีสคริปต์ signing และ verification

# NP Create Studio — Secure Production Refactor

ชุดไฟล์นี้คือโครงสร้างใหม่สำหรับนำโปรเจกต์เดิมมา Clone/Refactor เป็น Python project ที่ปลอดภัยกว่า ดูแลง่ายกว่า และพร้อมต่อยอดระดับ Production

## จุดที่ปรับจากโปรเจกต์เดิม

- แยก `UI / Services / Infrastructure / Domain / Web` ออกจากกัน
- เพิ่ม `SubprocessRunner` กลาง: ไม่ใช้ `shell=True`, มี allowlist, timeout, env sanitize, redacted log
- เพิ่ม `ToolchainResolver` + `tools_manifest.json`: ตรวจ SHA256 ของ `.exe/.dll/.jar/.apk` ก่อนใช้งาน
- เพิ่ม `safe_extract_zip`: กัน path traversal, absolute path, Windows drive path, symlink/hardlink, zip bomb เบื้องต้น
- เพิ่ม local dashboard token middleware: ป้องกัน API ภายในเครื่องถูกเรียกโดยเว็บอื่นแบบสุ่ม
- เพิ่ม secure storage abstraction สำหรับ token/license/OAuth secret
- เพิ่ม SQLite migration/schema version
- เพิ่ม tests เบื้องต้นสำหรับ security layer

## การเริ่มพัฒนา

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -e .[dev]
pytest
python -m npcreate_studio
```

## หมายเหตุสำคัญด้าน Production

ไฟล์นี้เป็น scaffold สำหรับพัฒนา ไม่ได้รวม bundled tools จากโปรเจกต์เดิม เช่น ADB, FFmpeg, MediaMTX, scrcpy, JDK, LSPatch, APK ให้เพิ่มใน `vendor/windows/` แล้วสร้าง manifest ด้วย:

```bash
python scripts/generate_tools_manifest.py --root vendor/windows --out tools_manifest.json
python scripts/verify_bundled_tools.py --root vendor/windows --manifest tools_manifest.json
```

ก่อนปล่อยลูกค้าจริง ควรทำ code signing, dependency lock, installer signing, SBOM และตรวจ compliance ของ workflow ที่เกี่ยวข้องกับ third-party platform


## Version 2.1.0: License Backend + Signed Patch Updates

เพิ่มระบบหลังบ้านสำหรับ:

- สร้าง License Key รายเดือน
- ต่ออายุ License
- ผูกการใช้งานเฉพาะคอม/โทรศัพท์
- ขอปลดอุปกรณ์โดย Admin
- แจ้งข่าวสารถึงโปรแกรมลูกค้า
- ปล่อย Patch Update แบบ signed manifest + SHA256

ดูรายละเอียดที่:

- `LICENSE_UPDATE_REFACTOR_REPORT_TH.md`
- `docs/LICENSE_UPDATE_BACKEND_TH.md`
- `docs/FILE_STRUCTURE_LICENSE_UPDATE_TH.md`

รัน Backend แบบ dev:

```bash
set NPCREATE_BACKEND_ENV=development
set NPCREATE_BACKEND_ADMIN_TOKEN=dev_admin_token_please_change_123456
set NPCREATE_BACKEND_APP_API_KEY=dev_app_api_key_please_change_123456
set NPCREATE_BACKEND_KEY_PEPPER=dev_key_pepper_please_change_123456
npcreate-backend
```

## เพิ่มเติมในเวอร์ชัน 2.2.0: Device Policy + Auto Billing

ระบบหลังบ้านรองรับการกำหนดจำนวนเครื่องแบบอิสระต่อ License ผ่าน `device_policies` เช่น 1 คอม + 1 มือถือ หรือ 2 คอม + 3 มือถือ โดยไม่ต้องแก้ Source Code

ระบบ License รายเดือนรองรับการต่ออายุอัตโนมัติจาก Payment Webhook ที่ตรวจลายเซ็นแล้ว พร้อม idempotency ป้องกัน webhook ซ้ำต่ออายุซ้ำ

เอกสารหลัก:

- `docs/AUTO_BILLING_DEVICE_POLICY_TH.md`
- `docs/BACKEND_API_BILLING_REFERENCE_TH.md`
- `AUTO_BILLING_DEVICE_POLICY_REPORT_TH.md`

คำสั่งจำลอง Webhook:

```bash
python scripts/simulate_payment_webhook.py ^
  --base-url http://127.0.0.1:8088 ^
  --secret dev_payment_webhook_secret_please_change_123456 ^
  --provider manual ^
  --provider-payment-id pay_test_001 ^
  --provider-subscription-id sub_customer_001 ^
  --amount-satangs 1590000
```


## Version 2.4.0: Enterprise Admin + PostgreSQL + MFA

เพิ่มรายการตาม Production roadmap ครบ 8 ข้อ:

1. Admin Web Dashboard จริงที่ `/admin`
2. PostgreSQL backend ผ่าน `NPCREATE_BACKEND_DATABASE_URL`
3. Admin Login + MFA แทนการใช้ Admin Token เดียว
4. Payment Gateway adapters สำหรับ Stripe / Omise / 2C2P / GB Prime Pay
5. Background Billing Job สำหรับ past_due / grace period / suspend อัตโนมัติ
6. Log Viewer / Error Report ทั้งใน Client UI และ Admin Dashboard
7. Windows Installer + Code Signing scripts
8. Toast Notification ใน Client UI

เอกสารหลัก: `docs/ENTERPRISE_PRODUCTION_UPGRADE_TH.md` และ `ENTERPRISE_SECURITY_UI_REPORT_TH.md`

สร้าง Admin คนแรก:

```bash
PYTHONPATH=src python scripts/admin_create_user.py --email admin@example.com --password "StrongPasswordHere"
```

รัน Backend Dev:

```bash
set NPCREATE_BACKEND_ENV=development
set NPCREATE_BACKEND_DATABASE_URL=
set NPCREATE_BACKEND_KEY_PEPPER=dev_key_pepper_please_change_123456
set NPCREATE_BACKEND_APP_API_KEY=dev_app_api_key_please_change_123456
npcreate-backend
```

Production PostgreSQL:

```bash
set NPCREATE_BACKEND_DATABASE_URL=postgresql://npcreate:STRONG_PASSWORD@db.example.com:5432/npcreate
```

## Version 2.6.0: Client Stack Feature Parity

ปิด gap ฝั่ง client ทั้งหมดเทียบกับ legacy `livemobillrerun` —
สตรีมวิดีโอผ่าน FFmpeg → 1-client TCP server → adb reverse → โทรศัพท์,
ปุ่ม TikTok Live Screen-Share 1 คลิก, Per-device rotation presets,
scrcpy mirror, RTMP push, signed self-update + atomic rollback,
และ portable state backup/restore — ครบทุก workflow

รายละเอียดทั้งหมด: `RELEASE_NOTES_v2.6.0.md`

ฝั่ง Android receiver แยกเป็น repo พี่น้องที่
`../npcreate_studio_android/` (Kotlin, package
`com.npcreate.studio.receiver`) — โปรโตคอลสื่อสาร (raw H.264 Annex-B
ผ่าน `adb reverse tcp:8888`, YUV file ที่
`/data/data/com.npcreate.studio.receiver/files/vcam.yuv`) เอกสาร
อยู่ใน README ของ repo นั้น

หน้าหลักที่เพิ่มใน Client GUI:

- **เริ่มต้น (Onboarding)** — wizard 5 ขั้น (License → Activate →
  เลือกอุปกรณ์ → Bridge → Ready) — first-run จะถูก redirect มาที่นี่อัตโนมัติ
- **Live Streaming** — เลือก source video, เริ่ม FFmpeg + TCP server,
  ดู stall watchdog (8 วินาที), 🎬 ปุ่ม TikTok 1 คลิก
- **Stream (RTMP)** — push ไป ingest URL ภายนอก (TikTok / YouTube)
  โดยไม่ต้องผ่านโทรศัพท์
- **ผูกอุปกรณ์** — แสดง devices ที่ผ่าน adb authorization
  พร้อมปุ่ม 🪞 Mirror ต่อ row
- **Device Profiles** — CRUD editor สำหรับ rotation presets ต่อรุ่นโทรศัพท์
- **อัปเดตโปรแกรม** — Background poller + manual check, ตรวจ Ed25519
  signature ก่อน apply, atomic swap พร้อม rollback
- **Backup / Restore** — สำรอง `device_profiles.json` +
  `client_state.json` เป็น ZIP, preview manifest ก่อน restore

Suite: **416 unit tests + 4 Postgres integration** ผ่านบน Python
3.11 / 3.12 / 3.13

ฝั่ง Android setup:

```bash
cd ../npcreate_studio_android
./gradlew :app:assembleDebug
./gradlew :app:installDebug
```

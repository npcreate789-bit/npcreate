# โครงสร้างไฟล์ใหม่หลังเพิ่มระบบ License + Update

```text
src/npcreate_studio/
├── core/                         # settings, security, errors
├── domain/                       # dataclass / business entities
│   └── licenses.py               # License, DeviceIdentity, News, UpdateInfo
├── infrastructure/               # db, secure store, subprocess, toolchain
├── services/
│   ├── client_state_service.py   # local state ของ client
│   ├── device_identity.py        # fingerprint คอม/มือถือ
│   ├── license_client.py         # activate / heartbeat / release request
│   ├── notification_service.py   # จัดการข่าวสารที่อ่านแล้ว
│   └── update_client.py          # ตรวจและดาวน์โหลด patch
├── ui/                           # Desktop UI
└── web/                          # local dashboard

src/npcreate_backend/
├── app.py                        # FastAPI factory
├── auth.py                       # admin token + activation bearer token
├── db.py                         # SQLite schema/migration
├── models.py                     # Pydantic request/response
├── routes_admin.py               # API สำหรับ Admin
├── routes_public.py              # API สำหรับ Client
├── security.py                   # license key hash, token, signing
└── settings.py                   # backend env settings

scripts/
├── admin_create_license.py       # CLI สร้าง License Key
├── publish_update_manifest.py    # CLI ประกาศ update manifest
├── generate_tools_manifest.py
└── verify_bundled_tools.py
```
```

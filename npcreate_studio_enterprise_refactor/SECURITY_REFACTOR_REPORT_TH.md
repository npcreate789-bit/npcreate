# NP Create — วิเคราะห์โครงสร้าง / ช่องโหว่ / ไฟล์ที่ปรับแล้วสำหรับพัฒนาต่อ

> ตรวจจากไฟล์ ZIP เดิมแบบ Static Audit เท่านั้น ไม่ได้รัน `.exe`, `.apk`, `.jar`, ADB, FFmpeg, MediaMTX, scrcpy หรือไฟล์ executable ใด ๆ

## 1. สรุปสิ่งที่ตรวจพบจากโปรเจกต์เดิม

โปรเจกต์เดิมเป็น Python Desktop Application สำหรับ Windows ใช้ `customtkinter` เป็น UI หลัก มี Embedded FastAPI Dashboard และ bundle เครื่องมือจำนวนมาก เช่น ADB, FFmpeg, scrcpy, MediaMTX, JDK, LSPatch และ APK

### Risk scan เบื้องต้นจาก source เดิม

| รายการที่ตรวจ | จำนวนที่พบ | ไฟล์ที่เกี่ยวข้องหลัก |
|---|---:|---|
| เรียก `subprocess.run/Popen` | 63 จุด | `adb.py`, `ffmpeg_streamer.py`, `hook_mode.py`, `lspatch_pipeline.py`, `rtmp_server.py`, `scrcpy_mirror.py`, `ui/studio_pages.py` ฯลฯ |
| `shell=True` | 1 จุด | `ui/studio_pages.py` |
| การใช้งาน ZIP / extraction | 14 จุด | `auto_update.py`, `backup_restore.py`, `log_setup.py`, `lspatch_pipeline.py`, `scrcpy_installer.py` |
| Network calls | 24 จุด | `auto_update.py`, `license_server.py`, `scrcpy_installer.py`, `webapp/tiktok_shop.py` |
| FastAPI routes | 8 route | `webapp/server.py` |
| `os.system` | 2 จุด | `log_setup.py` |
| `eval/exec` | 0 จุด | ไม่พบ |
| `pickle` | 0 จุด | ไม่พบ |

## 2. จุดที่ควรเพิ่มเติมก่อน Production

### 2.1 Subprocess ต้องรวมศูนย์

**ปัญหา:** โปรเจกต์เดิมเรียก ADB/FFmpeg/Java/scrcpy/MediaMTX หลายไฟล์ ทำให้ควบคุม timeout, logging, env, allowlist และ error handling ยาก

**สิ่งที่ปรับให้แล้ว:**

- เพิ่ม `src/npcreate_studio/infrastructure/subprocess_runner.py`
- บังคับไม่ใช้ `shell=True`
- มี executable allowlist
- มี sanitized environment
- มี timeout default
- redact log ก่อนบันทึก

### 2.2 Bundled Tools ต้องตรวจ hash

**ปัญหา:** มี `.exe/.dll/.jar/.apk` จำนวนมาก ถ้าไฟล์ถูกแก้หรือปลอม จะเสี่ยงมากก่อนเรียกใช้งาน

**สิ่งที่ปรับให้แล้ว:**

- เพิ่ม `tools_manifest.json`
- เพิ่ม `src/npcreate_studio/infrastructure/toolchain.py`
- เพิ่ม `scripts/generate_tools_manifest.py`
- เพิ่ม `scripts/verify_bundled_tools.py`

### 2.3 ZIP / Update / Backup ต้องกัน path traversal เข้มขึ้น

**ปัญหา:** เดิมกัน `..` บางจุดแล้ว แต่ควรเพิ่มการกัน absolute path, Windows drive path, symlink/special file, zip bomb

**สิ่งที่ปรับให้แล้ว:**

- เพิ่ม `safe_join`
- เพิ่ม `is_safe_archive_member`
- เพิ่ม `safe_extract_zip`
- เพิ่ม limit จำนวนไฟล์ / ขนาด archive / ขนาดหลังแตกไฟล์

### 2.4 Dashboard API ต้องมี local token

**ปัญหา:** แม้เปิดที่ localhost แต่เว็บอื่นใน browser อาจยิง request มาที่ local service ได้

**สิ่งที่ปรับให้แล้ว:**

- เพิ่ม `src/npcreate_studio/web/auth.py`
- เพิ่ม `LocalTokenAuthMiddleware`
- block client ที่ไม่ใช่ loopback
- API สำคัญต้องส่ง `x-npcreate-token`

### 2.5 OAuth / Token / License ต้องไม่เก็บ plain text

**ปัญหา:** ถ้าต่อ TikTok Shop OAuth จริง ห้ามเก็บ access token / refresh token เป็น plain SQLite

**สิ่งที่ปรับให้แล้ว:**

- เพิ่ม `src/npcreate_studio/infrastructure/secure_store.py`
- encrypted-at-rest fallback ด้วย Fernet
- ใส่ note ให้เปลี่ยนเป็น Windows DPAPI / Credential Manager ตอนทำ installer production จริง

### 2.6 ปิด Demo Route ใน Production

**ปัญหา:** `/api/demo/seed` และ `/api/demo/clear` ไม่ควรเปิดใน production

**สิ่งที่ปรับให้แล้ว:**

- เพิ่ม `Settings.enable_demo_routes = False`
- ถ้า `env=production` จะปิด route demo

### 2.7 แยก UI จาก Business Logic

**ปัญหา:** `studio_pages.py` ใหญ่มาก ทำให้แก้ต่อยาก และ UI ปน business logic

**สิ่งที่ปรับให้แล้ว:**

- แยก `ui/pages/*`
- แยก `ui/components/*`
- เพิ่ม `services/*` สำหรับ workflow
- เพิ่ม `domain/*` สำหรับ model กลาง
- เพิ่ม `infrastructure/*` สำหรับระบบต่ำ เช่น db, subprocess, toolchain

## 3. โครงสร้างใหม่ที่ปรับให้แล้ว

```text
npcreate_studio_secure_refactor/
├── pyproject.toml
├── README.md
├── .env.example
├── tools_manifest.json
├── legacy_migration_map.json
├── scripts/
│   ├── generate_tools_manifest.py
│   └── verify_bundled_tools.py
├── docs/
│   ├── SECURITY_AUDIT_TH.md
│   ├── MIGRATION_PLAN_TH.md
│   ├── PRODUCTION_CHECKLIST_TH.md
│   ├── ARCHITECTURE_TH.md
│   └── FILE_STRUCTURE_TH.md
├── src/npcreate_studio/
│   ├── app.py
│   ├── core/
│   ├── domain/
│   ├── infrastructure/
│   ├── services/
│   ├── ui/
│   └── web/
└── tests/unit/
```

## 4. ไฟล์สำคัญที่เพิ่ม/ปรับ

| ไฟล์ | หน้าที่ |
|---|---|
| `core/security.py` | hash, safe path, safe zip extract, token, compare digest |
| `core/settings.py` | config production, dashboard host validation, app data path |
| `core/logging.py` | structured JSON logging + redaction |
| `infrastructure/subprocess_runner.py` | subprocess กลาง ปลอดภัยกว่าเดิม |
| `infrastructure/toolchain.py` | resolve + verify bundled tools SHA256 |
| `infrastructure/secure_store.py` | เก็บ secret/token แบบ encrypted-at-rest |
| `infrastructure/db.py` | SQLite connection + migration version |
| `web/auth.py` | local token middleware |
| `web/api.py` | FastAPI app พร้อมปิด demo routes ใน production |
| `services/updater_service.py` | update flow ที่ใช้ safe extraction/signature/hash |
| `services/backup_service.py` | backup/restore แบบ safe member check |
| `services/license_service.py` | license verify ด้วย Ed25519 |
| `scripts/generate_tools_manifest.py` | สร้าง manifest hash จาก vendor tools |
| `scripts/verify_bundled_tools.py` | ตรวจ manifest ก่อน release/ก่อนใช้งาน |
| `tests/unit/*` | test security/toolchain/settings เบื้องต้น |

## 5. ผลตรวจหลังปรับ

- `python -m compileall` ผ่าน
- `pytest` ผ่าน 5 tests
- ไม่ได้รวม vendor tools จริงไว้ใน package ใหม่ เพื่อความปลอดภัยและลดขนาดไฟล์
- ต้องนำ tools จริงจากโปรเจกต์เดิมไปวางใน `vendor/windows/` แล้ว generate manifest ใหม่ก่อนใช้งานจริง

## 6. วิธีนำไปพัฒนาต่อ

```bash
cd npcreate_studio_secure_refactor
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
pytest
```

ถ้าจะนำ ADB/FFmpeg/MediaMTX/scrcpy/JDK/APK จากโปรเจกต์เดิมมาใช้:

```bash
mkdir -p vendor/windows
# copy tools ที่ผ่านการตรวจสอบมาใส่ vendor/windows
python scripts/generate_tools_manifest.py --root vendor/windows --out tools_manifest.json
python scripts/verify_bundled_tools.py --root vendor/windows --manifest tools_manifest.json
```

## 7. สิ่งที่ต้องทำต่อก่อนปล่อยลูกค้า

1. ย้าย logic เดิมเข้า service ทีละส่วน ห้ามย้ายแบบทั้งไฟล์ใหญ่
2. ทุก ADB/FFmpeg/Java call ต้องผ่าน `SubprocessRunner`
3. ทุก tool path ต้องผ่าน `ToolchainResolver`
4. ทุก ZIP extraction ต้องใช้ `safe_extract_zip`
5. TikTok/OAuth token ต้องเก็บผ่าน `SecureStore` หรือ Windows Credential Manager
6. ทำ dependency lock เช่น `uv.lock` หรือ `requirements.lock.txt`
7. ทำ code signing / installer signing
8. ทำ SBOM และ third-party license notice
9. ทำ CI: ruff, mypy, pytest, bandit, pip-audit
10. ตรวจ compliance/terms ของ workflow ที่เกี่ยวข้องกับแพลตฟอร์ม third-party ก่อนขาย Production

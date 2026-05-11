# วิเคราะห์โครงสร้างและช่องโหว่ — NP Create Customer Bundle v1.8.4

> ตรวจแบบ Static Audit เท่านั้น ไม่ได้รัน `.exe`, `.apk`, `.jar`, ADB, FFmpeg หรือ MediaMTX

## ภาพรวมที่พบจากโปรเจกต์เดิม

- โปรเจกต์หลักเป็น Python Desktop App ใช้ `customtkinter`
- มี Embedded Dashboard ด้วย FastAPI เปิดที่ `127.0.0.1:8765`
- มี bundled tools จำนวนมาก เช่น ADB, FFmpeg, scrcpy, MediaMTX, JDK, LSPatch, APK
- มีระบบ License, Auto Update, Backup/Restore, Diagnostic Log, TikTok Shop Dashboard
- UI หลักรวมใน `src/ui/studio_pages.py` ขนาดใหญ่มาก ทำให้แก้ต่อยากและเสี่ยง regression

## จุดที่ควรเพิ่มเติมก่อน Production

### 1. Toolchain Integrity

เดิมมี `.exe/.dll/.jar/.apk` จำนวนมาก แต่ควรบังคับตรวจ SHA256 ก่อนเรียกใช้งาน

สิ่งที่เพิ่มในโครงสร้างใหม่นี้:

- `tools_manifest.json`
- `ToolchainResolver`
- `scripts/generate_tools_manifest.py`
- `scripts/verify_bundled_tools.py`

### 2. Subprocess Security

เดิมมีการเรียก `subprocess.run/Popen` หลายจุด เช่น ADB, FFmpeg, scrcpy, MediaMTX, Java/LSPatch ทำให้ควบคุม timeout/log/env/allowlist ยาก

สิ่งที่เพิ่ม:

- `infrastructure/subprocess_runner.py`
- ไม่ใช้ `shell=True`
- จำกัด executable allowlist
- จำกัด root ของ bundled tools
- sanitize environment
- redacted log
- timeout default

### 3. ZIP / Update / Backup Safety

เดิมมีการกัน `..` บางจุด แต่ Production ควรกันเพิ่ม:

- absolute path `/tmp/...`
- Windows drive path `C:\...`
- symlink/hardlink/special file
- zip bomb เบื้องต้น เช่นจำนวนไฟล์และขนาดแตกไฟล์เกิน limit

สิ่งที่เพิ่ม:

- `core/security.py::safe_extract_zip`
- `core/security.py::is_safe_archive_member`
- `core/security.py::safe_join`

### 4. Dashboard Local Auth

ถึงแม้ Dashboard bind ที่ `127.0.0.1` แต่ browser/เว็บอื่นในเครื่องอาจยิง request เข้ามาได้ จึงควรมี local token/CSRF-like guard

สิ่งที่เพิ่ม:

- `web/auth.py::LocalTokenAuthMiddleware`
- `/api/health` เปิดได้ แต่ API สำคัญต้องมี `x-npcreate-token`
- block client ที่ไม่ใช่ loopback

### 5. Token / OAuth / License Storage

ถ้าใช้ TikTok Shop OAuth จริง ห้ามเก็บ token plain text ใน SQLite/ไฟล์ config

สิ่งที่เพิ่ม:

- `infrastructure/secure_store.py`
- encrypted-at-rest ด้วย Fernet fallback
- หมายเหตุให้เปลี่ยนเป็น Windows DPAPI/Credential Manager ตอน build installer จริง

### 6. Config & Demo Route

Demo endpoint ควรปิดใน production เสมอ

สิ่งที่เพิ่ม:

- `Settings.enable_demo_routes = False`
- ถ้า `env=production` แล้วยิง demo route จะได้ 403
- `dashboard_host` validate ให้เป็น localhost เท่านั้น

### 7. Database Migration

เดิม dashboard SQLite ควรมี schema version ชัดเจนก่อนเพิ่มตารางจริง

สิ่งที่เพิ่ม:

- `infrastructure/db.py`
- `app_meta.schema_version`
- migration table แบบ lightweight

## ระดับความเสี่ยงที่ควรแก้ก่อนปล่อยลูกค้า

| ระดับ | จุดเสี่ยง | แนวทางป้องกันที่ใส่ในโครงสร้างใหม่ |
|---|---|---|
| สูง | bundled tools ถูกเปลี่ยน/ปลอม | SHA256 manifest + verify ก่อนเรียกใช้ |
| สูง | subprocess เรียกกระจาย/ควบคุมยาก | SubprocessRunner กลาง + allowlist + timeout |
| สูง | update/backup zip path traversal | safe_extract_zip + safe_join |
| กลาง-สูง | token/OAuth plain text | SecureStore + DPAPI adapter ใน production |
| กลาง | dashboard local API ถูกเว็บอื่นเรียก | Local token middleware |
| กลาง | demo endpoints หลุดใน production | feature flag + env guard |
| กลาง | UI ไฟล์ใหญ่ แก้ยาก | แยก pages/components/services |
| กลาง | dependency drift | pyproject + dev audit tools + lock file ตอน release |

## สิ่งที่ยังต้องทำจริงก่อน Production

1. นำ implementation เดิมย้ายเข้า service ทีละส่วน
2. สร้าง `tools_manifest.json` จาก vendor tools จริง
3. ทำ dependency lock เช่น `uv.lock` หรือ `requirements.lock.txt`
4. ทำ code signing / installer signing
5. ทำ SBOM + third-party license notice
6. ทำ CI: ruff, mypy, pytest, bandit, pip-audit
7. ตรวจ compliance/terms สำหรับ workflow ที่เกี่ยวข้องกับ third-party app/platform

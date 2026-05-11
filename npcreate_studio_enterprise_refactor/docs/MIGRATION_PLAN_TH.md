# แผนย้ายจากโปรเจกต์เดิมมาโครงสร้างใหม่

## Phase 1 — Stabilize

ย้ายเฉพาะส่วนที่ไม่เปลี่ยน business logic:

| จากไฟล์เดิม | ไปไฟล์ใหม่ |
|---|---|
| `src/adb.py` | `services/adb_service.py` + `infrastructure/subprocess_runner.py` |
| `src/platform_tools.py` | `infrastructure/toolchain.py` |
| `src/ffmpeg_streamer.py` | `services/media_service.py` |
| `src/rtmp_server.py` | `services/media_service.py` หรือ `services/stream_service.py` |
| `src/license_key.py` | `services/license_service.py` |
| `src/backup_restore.py` | `services/backup_service.py` |
| `src/auto_update.py` | `services/updater_service.py` |
| `src/webapp/server.py` | `web/api.py` + `web/server.py` |
| `src/webapp/db.py` | `infrastructure/db.py` |
| `src/ui/studio_pages.py` | `ui/pages/*.py` + `ui/components/*.py` |

## Phase 2 — Secure

- บังคับทุก subprocess ผ่าน `SubprocessRunner`
- บังคับทุก tool path ผ่าน `ToolchainResolver`
- เปลี่ยน ZIP extraction ทั้งหมดมาใช้ `safe_extract_zip`
- ใส่ local dashboard token
- ย้าย token/secret เข้า `SecureStore`

## Phase 3 — Production Release

- Build installer
- Sign executable/installer
- Generate `tools_manifest.json`
- Run test/audit
- ทำ release note + rollback plan

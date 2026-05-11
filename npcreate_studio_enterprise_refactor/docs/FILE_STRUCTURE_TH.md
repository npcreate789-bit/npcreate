# โครงสร้างไฟล์ใหม่ที่แนะนำ

ดูไฟล์ `UPDATED_FILE_TREE.txt` สำหรับรายการเต็ม

## โฟลเดอร์หลัก

- `src/npcreate_studio/core` — security, settings, logging, errors
- `src/npcreate_studio/domain` — model กลาง เช่น device, stream, license, sales
- `src/npcreate_studio/infrastructure` — db, subprocess, toolchain, secure store, filesystem
- `src/npcreate_studio/services` — business workflow
- `src/npcreate_studio/ui` — customtkinter UI
- `src/npcreate_studio/web` — FastAPI dashboard
- `scripts` — helper สำหรับ build/release
- `tests` — unit tests
- `docs` — เอกสารวิเคราะห์และ checklist

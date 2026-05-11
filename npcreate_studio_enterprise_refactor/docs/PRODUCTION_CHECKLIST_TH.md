# Production Checklist

## Security

- [ ] ไม่มี `shell=True` ยกเว้นมีเหตุผลและ review แล้ว
- [ ] ทุก bundled tool มี SHA256 ใน `tools_manifest.json`
- [ ] ตรวจ hash ก่อนเรียกใช้ ADB/FFmpeg/scrcpy/MediaMTX/JDK/LSPatch/APK
- [ ] Dashboard bind เฉพาะ `127.0.0.1`
- [ ] API ภายในมี local token
- [ ] Demo routes ปิดใน production
- [ ] OAuth/token/license secrets ไม่เก็บ plain text
- [ ] ZIP extraction ใช้ `safe_extract_zip`
- [ ] Diagnostic zip redact token/license/private key
- [ ] Backup ไม่รวม `.private_key`, `master.key`, OAuth token

## Reliability

- [ ] UI ไม่ freeze ระหว่าง task หนัก
- [ ] subprocess มี timeout/retry/backoff
- [ ] มี structured log ต่อ task
- [ ] SQLite มี migration version
- [ ] Auto-update rollback ได้
- [ ] Backup/restore atomic

## Release

- [ ] Lock dependency
- [ ] Run `pytest`
- [ ] Run `ruff check .`
- [ ] Run `mypy src`
- [ ] Run `bandit -r src`
- [ ] Run `pip-audit`
- [ ] Build installer
- [ ] Sign code/installer
- [ ] ทำ SBOM/license notice
- [ ] Smoke test บนเครื่อง Windows สะอาด

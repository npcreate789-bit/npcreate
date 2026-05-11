# Architecture

```text
UI Layer        customtkinter pages/components
Service Layer   business workflow เช่น device, stream, license, backup, update
Infrastructure  subprocess, toolchain, db, filesystem, secure store
Domain          dataclass/model ที่ไม่ผูกกับ UI หรือ subprocess
Web             FastAPI dashboard bind localhost + local token
```

หลักการคือ UI ห้ามเรียก ADB/FFmpeg/Java โดยตรง ให้เรียกผ่าน Service และ Service เรียกผ่าน Infrastructure เท่านั้น

# UX/UI Structure — NP Create Studio

## เป้าหมาย UI

UI ชุดนี้ออกแบบให้ลูกค้าใช้งานง่ายขึ้น โดยลดเมนูที่ซับซ้อนและแสดงสถานะสำคัญแบบเห็นทันที ได้แก่ License, อุปกรณ์ที่ผูก, อัปเดต, ข่าวสาร และการตั้งค่า

## โครงสร้างหน้า

```text
MainWindow
├── Sidebar Navigation
│   ├── ภาพรวมระบบ
│   ├── License
│   ├── ผูกอุปกรณ์
│   ├── อัปเดตโปรแกรม
│   ├── ข่าวสาร
│   └── ตั้งค่า
└── Content Area
    ├── DashboardPage
    ├── LicensePage
    ├── DevicesPage
    ├── UpdatesPage
    ├── NewsPage
    └── SettingsPage
```

## หลักการออกแบบ

- Business logic ต้องอยู่ใน `services/` ไม่ฝังใน UI
- UI page ทำหน้าที่แสดงผลและเรียก service เท่านั้น
- ทุก action สำคัญควรมีสถานะสำเร็จ/ผิดพลาดที่อ่านง่าย
- หลีกเลี่ยงข้อความเทคนิคที่ลูกค้าไม่เข้าใจ เช่น fingerprint hash ให้ใช้คำว่า “เครื่องนี้”, “โทรศัพท์ที่ผูก” แทน
- สีสถานะควรคงที่: เขียว = ปลอดภัย/สำเร็จ, เหลือง = รอตรวจสอบ, แดง = มีปัญหา

## ไฟล์ที่เกี่ยวข้อง

```text
src/npcreate_studio/ui/main_window.py
src/npcreate_studio/ui/theme.py
src/npcreate_studio/ui/components/__init__.py
src/npcreate_studio/ui/pages/dashboard_page.py
src/npcreate_studio/ui/pages/license_page.py
src/npcreate_studio/ui/pages/devices_page.py
src/npcreate_studio/ui/pages/updates_page.py
src/npcreate_studio/ui/pages/news_page.py
src/npcreate_studio/ui/pages/settings_page.py
```

## ขั้นตอนต่อไปที่แนะนำ

1. เชื่อม `LicensePage` กับ `LicenseClient.activate()` แบบ background thread
2. เชื่อม `DevicesPage` กับ device heartbeat/status API
3. เชื่อม `UpdatesPage` กับ `UpdateClient` เพื่อ download/verify/install patch
4. เชื่อม `NewsPage` กับ `/api/v1/news`
5. เพิ่ม notification toast สำหรับ success/error
6. เพิ่ม loading state ป้องกันผู้ใช้กดซ้ำ

# Backend API Reference: NP Create License + Update

## Headers

Admin routes:

```text
X-Admin-Token: <strong-admin-token>
```

Client activation-protected routes:

```text
Authorization: Bearer <activation_token>
```

## Client Routes

### POST `/api/v1/licenses/activate`

ใช้ตอนลูกค้ากรอก License Key และลงทะเบียนเครื่อง

Request:

```json
{
  "license_key": "NP-XXXX-XXXX-XXXX-XXXX",
  "device_type": "pc",
  "device_fingerprint": "sha256...",
  "device_label": "Customer-PC / Windows 11",
  "device_metadata": {},
  "app_version": "2.1.0"
}
```

ถ้า License นี้ผูกอุปกรณ์ประเภทเดียวกันครบแล้ว ระบบจะตอบ `409 device limit reached`

### POST `/api/v1/licenses/heartbeat`

ให้ Client ส่งเป็นระยะ เช่น ทุกครั้งที่เปิดโปรแกรม หรือทุก 6-12 ชั่วโมง

### GET `/api/v1/news`

ดึงข่าวสารจาก Admin ไปแสดงในโปรแกรม

### POST `/api/v1/devices/release-request`

ลูกค้าส่งคำขอปลดเครื่องเดิมให้ Admin ตรวจ

### GET `/api/v1/updates/latest?channel=stable`

ให้ Client เช็กแพทช์ล่าสุด

## Admin Routes

### POST `/api/v1/admin/licenses`

สร้าง License Key รายเดือน

```json
{
  "customer_name": "Customer A",
  "customer_contact": "line: customer",
  "months": 1,
  "max_pc_devices": 1,
  "max_phone_devices": 1,
  "features": ["studio", "phone_bind", "updates"],
  "notes": ""
}
```

### POST `/api/v1/admin/licenses/{license_id}/renew`

ต่ออายุ License

```json
{
  "months": 1
}
```

### GET `/api/v1/admin/licenses`

ดู License ทั้งหมด

### GET `/api/v1/admin/licenses/{license_id}/devices`

ดูอุปกรณ์ที่ผูกกับ License

### POST `/api/v1/admin/devices/{device_id}/release`

ปลดอุปกรณ์เดิม เพื่อให้ลูกค้าลงทะเบียนเครื่องใหม่ได้

### POST `/api/v1/admin/news`

ส่งข่าวสารเข้าโปรแกรมลูกค้า

```json
{
  "title": "แจ้งอัปเดตระบบ",
  "body": "มีแพทช์ใหม่สำหรับปรับปรุงความเสถียร",
  "severity": "info",
  "audience": "all"
}
```

### POST `/api/v1/admin/updates`

ประกาศแพทช์ใหม่

```json
{
  "version": "2.1.1",
  "channel": "stable",
  "mandatory": false,
  "download_url": "https://your-domain.com/releases/patch-2.1.1.zip",
  "sha256": "64-char-sha256",
  "release_notes": "แก้ไขบั๊กและปรับปรุงระบบ"
}
```

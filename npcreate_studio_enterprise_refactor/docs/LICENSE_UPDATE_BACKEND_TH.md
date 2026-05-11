# ระบบอัปเดตแพทช์ + ระบบหลังบ้าน License รายเดือน

เอกสารนี้เป็น Blueprint สำหรับนำ Source Code ไปพัฒนาต่อระดับ Production โดยแยกเป็น 2 ฝั่ง

1. **Client App**: โปรแกรมบนเครื่องลูกค้า Windows/Python Desktop UI
2. **Backend API**: ระบบหลังบ้านสำหรับออก Key, ต่ออายุ, ผูกอุปกรณ์, ปลดอุปกรณ์, แจ้งข่าวสาร และปล่อย Patch Version

## เป้าหมายที่เพิ่มเข้ามา

- โปรแกรมสามารถตรวจสอบเวอร์ชันล่าสุดจาก Backend ได้
- รองรับ Patch Update แบบ signed manifest + SHA256
- Admin สามารถสร้าง License Key รายเดือน
- Admin สามารถต่ออายุรายเดือน
- License ผูกกับเครื่องคอมและโทรศัพท์ที่ลงทะเบียนแล้ว
- ถ้าลงทะเบียนแล้ว จะใช้กับอุปกรณ์อื่นไม่ได้จนกว่า Admin จะปลดเครื่องเดิม
- Backend ส่งข่าวสาร/ประกาศไปยังโปรแกรมได้
- Client ส่ง heartbeat เพื่อตรวจสอบสถานะ license, expiry, revoke, suspend

## Flow การลงทะเบียน

```text
ลูกค้าเปิดโปรแกรม
→ กรอก License Key
→ โปรแกรมสร้าง Device Fingerprint ของ PC
→ ถ้ามีมือถือ Android ต่ออยู่ โปรแกรมสร้าง Fingerprint ของ Phone
→ ส่งไป Backend
→ Backend ตรวจ Key / วันหมดอายุ / โควต้าอุปกรณ์
→ ถ้ายังไม่มีอุปกรณ์ประเภทนั้น ระบบ Bind เครื่องนี้
→ ถ้ามีเครื่องอื่นใช้โควต้าแล้ว ระบบปฏิเสธ และแจ้งให้ขอปลดจาก Admin
→ Backend คืน Activation Token
→ Client เก็บ Token ใน Secure Store
```

## Device Limit ที่แนะนำ

ค่าเริ่มต้น:

- `max_pc_devices = 1`
- `max_phone_devices = 1`

หมายความว่า 1 License ใช้ได้กับ 1 คอม + 1 โทรศัพท์ เท่านั้น

## Flow การปลดอุปกรณ์

```text
ลูกค้าเปลี่ยนเครื่อง / มือถือพัง / ลง Windows ใหม่
→ กดส่งคำขอปลดเครื่องในโปรแกรม
→ Backend บันทึก release_request
→ Admin ตรวจสอบ
→ Admin กด release device
→ Device เดิมกลายเป็น released
→ ลูกค้าจึง activate เครื่องใหม่ได้
```

## Flow การต่ออายุรายเดือน

```text
Admin เปิดหลังบ้าน
→ เลือก License
→ กด Renew +1 เดือน หรือจำนวนเดือนที่ต้องการ
→ Backend ขยาย expires_at จากวันหมดอายุเดิม
→ Client heartbeat ครั้งถัดไปจะเห็นวันหมดอายุใหม่
```

## ระบบ Update Patch

ระบบ Update ใช้ 3 ชั้นป้องกัน:

1. Backend เก็บ `version`, `download_url`, `sha256`, `signature`
2. Client ตรวจ signature ด้วย Ed25519 public key ที่ฝังไว้ในโปรแกรม
3. Client ดาวน์โหลด patch แล้วตรวจ SHA256 ก่อนแตกไฟล์ด้วย `safe_extract_zip`

ห้ามให้ Client เชื่อ URL โดยตรงโดยไม่ตรวจ signature และ hash

## API หลัก

### Client API

- `POST /api/v1/licenses/activate`
- `POST /api/v1/licenses/heartbeat`
- `GET /api/v1/news`
- `POST /api/v1/devices/release-request`
- `GET /api/v1/updates/latest?channel=stable`

### Admin API

ต้องส่ง Header:

```text
X-Admin-Token: <admin token>
```

Routes:

- `POST /api/v1/admin/licenses` สร้าง License Key
- `POST /api/v1/admin/licenses/{license_id}/renew` ต่ออายุ
- `GET /api/v1/admin/licenses` ดู License ทั้งหมด
- `GET /api/v1/admin/licenses/{license_id}/devices` ดูอุปกรณ์ที่ผูกอยู่
- `POST /api/v1/admin/devices/{device_id}/release` ปลดอุปกรณ์
- `POST /api/v1/admin/news` ส่งข่าวสาร
- `POST /api/v1/admin/updates` ประกาศแพทช์ใหม่

## ช่องโหว่ที่ต้องป้องกัน

### 1. License Key ถูกเดา / หลุด

สิ่งที่ทำไว้:

- สร้าง Key ด้วย `secrets`
- Backend ไม่เก็บ Key ดิบ แต่เก็บ HMAC-SHA256 + pepper
- Admin เห็น Key เฉพาะตอนสร้างครั้งแรก

### 2. เอา License ไปใช้หลายเครื่อง

สิ่งที่ทำไว้:

- ผูก `license_id + device_type + fingerprint_hash`
- แยกโควต้าคอมกับโทรศัพท์
- ถ้าโควต้าเต็ม จะ activate เครื่องใหม่ไม่ได้

### 3. Client แก้ไฟล์ให้ข้าม License

สิ่งที่ควรทำต่อ:

- Build เป็น signed executable
- Obfuscate เฉพาะส่วน license client ได้ในระดับหนึ่ง
- ตรวจ heartbeat เป็นระยะ
- ใช้ feature flag จาก server เปิด/ปิดฟังก์ชันสำคัญ

### 4. Update ถูกปลอม

สิ่งที่ทำไว้:

- Ed25519 signature
- SHA256 package
- safe zip extraction
- ไม่ใช้ shell command ตอน update

### 5. Admin Token หลุด

สิ่งที่ต้องทำตอน Deploy:

- ใช้ Admin Token ยาวมากกว่า 32 ตัวอักษร
- เก็บใน Secret Manager / Environment Variable
- หลังบ้านจริงควรเพิ่ม login + RBAC + audit log
- จำกัด IP Admin Panel ถ้าเป็นไปได้

## สิ่งที่ควรทำเพิ่มก่อนขายจริง

- ทำ Admin Web UI จริง เช่น `/admin` แยกสิทธิ์ login
- เพิ่ม audit log ทุก action ของ admin
- เพิ่ม payment webhook เพื่อ renew อัตโนมัติ
- เพิ่ม rate limit ต่อ IP และต่อ license key
- เพิ่ม backup database อัตโนมัติ
- เพิ่ม monitoring/alert เช่น license activation fail rate
- ทำ code signing ทั้ง Client และ Installer
- ทำ HTTPS เท่านั้น ห้ามใช้ HTTP ใน Production

# คู่มือใช้งาน OIDA Next

คู่มือย่อภาษาไทยเปิดได้จากปุ่ม **คู่มือ** บนแถบด้านบนของ OIDA, PM,
QA, Document และ Infra เนื้อหาจะเปลี่ยนตามระบบที่กำลังใช้งาน เอกสารนี้เป็น
ฉบับรวมสำหรับผู้ดูแลระบบ

## เริ่มใช้งาน

1. เปิด `https://oida-next.kanphong.com` และล็อกอิน OIDA หนึ่งครั้ง
2. เลือก AI provider ในกล่อง **AI model & DeepSeek API key**
3. สำหรับ DeepSeek ให้เลือก `DeepSeek API`, ใช้ model `deepseek-chat`, วาง key แล้วกด **Save AI settings**
4. กด **Test connection** ต้องเห็น `connection passed` โดยระบบจะไม่แสดง key กลับมา

## สร้างและส่งงาน

1. กรอกชื่อโครงการและ requirement ซึ่งระบุผลลัพธ์ ขอบเขต ข้อจำกัด และเกณฑ์ยอมรับ
2. กด **Generate AI draft** และรอจนสถานะเป็น `DRAFT`
3. ตรวจ PM tasks, QA suites/cases, Document requirements และ Infra components ใน JSON
4. แก้ไขแล้วกด **Save edited draft** หากจำเป็น จากนั้นตรวจ plan ใหม่อีกครั้ง
5. กด **Approve and distribute** ระบบจะส่ง exact plan hash ไปทั้งสี่โมดูล
6. เมื่อเป็น `APPROVED` ให้กด **Run full-loop check** และตรวจว่าเป็น `PASS`

## แก้ requirement ที่อนุมัติแล้ว

เปิด **Request an AI revision**, อธิบายเฉพาะสิ่งที่เปลี่ยน แล้วตรวจ diff เครื่องหมาย `+`, `~`, `−` เลือกโมดูลที่ต้องอัปเดตและกด **Approve selected changes** การลบเป็นงาน manual เพื่อป้องกัน AI ลบข้อมูลที่อนุมัติแล้ว เมื่อจบให้รัน full-loop check บน revision อีกครั้ง

## Retry และสถานะผิดปกติ

- `GENERATING`: AI กำลังสร้าง draft และยังไม่เปลี่ยนงานที่อนุมัติแล้ว
- `PARTIAL`: บางรายการส่งไม่สำเร็จ กด **Retry unfinished items** ระบบจะข้ามรายการที่สำเร็จแล้ว
- `FAILED`: การสร้าง AI ล้มเหลว กด **Retry AI generation**
- Local Agent offline หลัง restart: ออกจากระบบและล็อกอิน OIDA ใหม่หนึ่งครั้งเพื่อปลดล็อก identity ที่เข้ารหัส
- DeepSeek ใช้ไม่ได้: ตรวจ provider/model แล้วกด **Test connection** ก่อนสร้าง draft

## ตรวจ production และ backup

รัน regression แบบ authenticated โดยไม่สร้างโครงการใหม่:

```bash
uv run python scripts/production_regression.py --output work/production-regression.json
```

รัน online backup และ restore ลงสำเนาแยกที่มี permission จำกัด:

```bash
uv run python scripts/backup_restore_drill.py
```

เก็บ OIDA password และ DeepSeek key ใน password manager ห้ามใส่ใน command, source code, log หรือเอกสารผลทดสอบ

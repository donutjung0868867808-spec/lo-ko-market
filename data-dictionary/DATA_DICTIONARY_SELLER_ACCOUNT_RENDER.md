# 3.6 พจนานุกรมข้อมูล (Data Dictionary)

เอกสารนี้จัดทำจากโครงสร้างฐานข้อมูลของระบบ Thin Dee โดยแสดงชนิดข้อมูล คีย์ และตารางอ้างอิงของบัญชีผู้ขาย

## ตารางที่ 3.1 ตารางข้อมูล `accounts_user`

**คำอธิบาย:** ข้อมูลบัญชีผู้ขาย จาก schema ฐานข้อมูล PostgreSQL บน Render (thin-dee-db) โดยระเบียนผู้ขายระบุด้วย role = farmer

| ลำดับ | ชื่อฟิลด์ | ชนิด | คำอธิบาย | Key | Reference |
|---:|---|---|---|:---:|---|
| 1 | id | BIGINT | รหัสประจำรายการ | PK |  |
| 2 | password | VARCHAR(128) | รหัสผ่านที่จัดเก็บแบบเข้ารหัส |  |  |
| 3 | last_login | TIMESTAMPTZ | วันและเวลาที่เข้าสู่ระบบล่าสุด (อนุญาตให้ว่าง) |  |  |
| 4 | is_superuser | BOOLEAN | สถานะผู้ดูแลระบบระดับสูง |  |  |
| 5 | username | VARCHAR(150) | ชื่อผู้ใช้สำหรับเข้าสู่ระบบ | UQ |  |
| 6 | first_name | VARCHAR(150) | ชื่อ |  |  |
| 7 | last_name | VARCHAR(150) | นามสกุล |  |  |
| 8 | email | VARCHAR(254) | อีเมล | UQ |  |
| 9 | is_staff | BOOLEAN | สถานะการเข้าถึงส่วนผู้ดูแลระบบ |  |  |
| 10 | is_active | BOOLEAN | สถานะเปิดใช้งาน |  |  |
| 11 | date_joined | TIMESTAMPTZ | วันและเวลาที่สมัครสมาชิก |  |  |
| 12 | role | VARCHAR(32) | บทบาทผู้ใช้: consumer, farmer, cooperative_staff หรือ owner |  |  |
| 13 | display_name | VARCHAR(150) | ชื่อที่ใช้แสดงในระบบหรือชื่อร้านค้า |  |  |
| 14 | phone | VARCHAR(30) | หมายเลขโทรศัพท์ |  |  |
| 15 | email_verified_at | TIMESTAMPTZ | วันและเวลาที่ยืนยันอีเมล (อนุญาตให้ว่าง) |  |  |
| 16 | privacy_accepted_at | TIMESTAMPTZ | วันและเวลาที่ยอมรับนโยบายความเป็นส่วนตัว (อนุญาตให้ว่าง) |  |  |
| 17 | terms_accepted_at | TIMESTAMPTZ | วันและเวลาที่ยอมรับข้อกำหนดการใช้งาน (อนุญาตให้ว่าง) |  |  |
| 18 | privacy_version | VARCHAR(20) | เวอร์ชันนโยบายความเป็นส่วนตัวที่ยอมรับ |  |  |
| 19 | terms_version | VARCHAR(20) | เวอร์ชันข้อกำหนดการใช้งานที่ยอมรับ |  |  |
| 20 | avatar | VARCHAR(100) | ไฟล์รูปโปรไฟล์ |  |  |
| 21 | birth_date | DATE | วันเกิด (อนุญาตให้ว่าง) |  |  |
| 22 | gender | VARCHAR(20) | เพศ |  |  |

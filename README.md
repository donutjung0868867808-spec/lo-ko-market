# ตลาดเกษตรชุมชน

คู่มือ Production รุ่นปัจจุบัน: [DEPLOY_PRODUCTION.md](DEPLOY_PRODUCTION.md)
ใช้ Blueprint ที่รวม ASGI, Redis และ Cron แทนขั้นตอนแผนฟรี/WSGI ด้านล่าง

เว็บซื้อขายสินค้าเกษตรโดยตรงระหว่างเกษตรกรชุมชนและผู้บริโภค พัฒนาด้วย Django, Django REST Framework, PostgreSQL, Cloudinary, Stripe และ Render

## ความสามารถหลัก

- ผู้บริโภค: ค้นหา ตะกร้า ชำระเงิน ติดตามพัสดุ รีวิว ขอคืนเงิน และรายงานปัญหา
- เกษตรกร: ส่งเอกสารยืนยัน ลงสินค้าแบบหลายรูป จัดการสต็อก และอัปเดตการจัดส่ง
- เจ้าหน้าที่ชุมชน: ดูและแก้ข้อมูลผู้ขาย สินค้า สต็อก คำสั่งซื้อ และรายงานเฉพาะชุมชน
- เจ้าของระบบ: จัดการสมาชิก ข่าวสาร การชำระเงิน Webhook และคืนเงิน
- ระบบ: ยืนยันอีเมล จำกัดการเดารหัสผ่าน จอง/คืนสต็อก ประวัติสถานะ และบันทึกเหตุการณ์ Stripe

## รันบนเครื่อง

ใช้คำสั่งตามลำดับ:

    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    npm install
    npm run build:css
    python manage.py migrate
    python manage.py createsuperuser
    python manage.py runserver

เปิด http://127.0.0.1:8000/

- เจ้าหน้าที่วิสาหกิจชุมชนเข้าสู่ระบบที่ /login/ และระบบจะเปิด /accounts/staff/ อัตโนมัติ
- เจ้าของระบบเข้า Django Admin ที่ /admin/ โดยตรง
- บัญชีเจ้าหน้าที่ไม่มีสิทธิ์เปิด Django Admin
- เจ้าของระบบเพิ่มเจ้าหน้าที่โดยสร้างผู้ใช้บทบาทเจ้าหน้าที่ แล้วผูกชุมชนในเมนูเจ้าหน้าที่ชุมชน

## งานประจำของระบบ

เรียกคำสั่งนี้เป็นระยะเพื่อยกเลิกคำสั่งซื้อที่หมดเวลาชำระและคืนสต็อก:

    python manage.py expire_orders
    python manage.py notify_low_stock

บน Production ควรตั้ง Scheduled Job ให้เรียกทุก 5 นาที แม้หน้าเว็บจะตรวจรายการหมดอายุให้อัตโนมัติเมื่อมีการเปิดหน้าคำสั่งซื้ออยู่แล้ว

## เตรียม Production

ตั้งค่าตาม .env.example โดยค่าที่ต้องมีจริงได้แก่ PostgreSQL, Cloudinary, Stripe, SMTP email, SECRET_KEY, ALLOWED_HOSTS และ CSRF_TRUSTED_ORIGINS

ตั้ง Stripe Webhook ไปที่:

    https://ชื่อโดเมน/payments/stripe/webhook/

เปิด event อย่างน้อย checkout.session.completed, checkout.session.expired, payment_intent.payment_failed, refund.created และ refund.updated

ตรวจความพร้อมก่อนเปิดระบบ:

    python manage.py check --deploy
    python manage.py check_production
    python manage.py test

หลัง Deploy ให้เปิด /health/ และตรวจว่าตอบ {"status": "ok"} จากนั้นทดสอบการสมัคร อีเมล ชำระเงินจริง การจัดส่ง และคืนเงินด้วยบัญชีทดสอบก่อนรับผู้ใช้จริง

## การสำรองข้อมูล

เปิดบริการสำรอง PostgreSQL ของผู้ให้บริการหรือใช้ pg_dump ทุกวัน เก็บสำเนาแยกจาก Render และทดสอบกู้คืนเป็นระยะ รูปภาพอยู่ใน Cloudinary จึงต้องกำหนดนโยบายสำรองและสิทธิ์เข้าถึงใน Cloudinary เพิ่มเติมด้วย

## API

- GET /api/products/
- POST /api/products/ สำหรับเกษตรกรที่ยืนยันแล้ว
- GET /api/orders/
- GET /api/communities/
- GET /api/categories/
- GET /api/me/

## ความพร้อมสำหรับใช้งานจริง

ระบบมี session แยกระหว่างเว็บทั่วไปกับ Django Admin, MFA ทางอีเมลสำหรับเจ้าของระบบ, สิทธิ์เจ้าหน้าที่ตามชุมชน, private document storage, Stripe webhook แบบ idempotent, Stripe Connect settlement, email outbox, audit log, ข้อจำกัดฐานข้อมูล, readiness endpoint และงานบำรุงรักษาแล้ว

คำสั่งงานประจำที่ควรเรียกทุก 5 นาที:

    python manage.py run_maintenance

ตรวจค่าก่อนเปิด Production:

    python manage.py check_production

รายละเอียดบัญชีภายนอก ตัวแปร Render, Stripe, การย้ายเอกสารส่วนตัว, backup และ smoke test อยู่ใน PRODUCTION_CHECKLIST.md

`render.yaml` เป็น Blueprint หลักที่รวมเว็บ PostgreSQL Redis และ Cron Job และใช้แผนแบบเสียเงินตามที่ระบุในไฟล์ ตรวจค่าใช้จ่ายบน Render ก่อนสร้างบริการ และไม่ต้อง deploy `render.cron.yaml` ซ้ำ

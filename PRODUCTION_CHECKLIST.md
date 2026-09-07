# รายการเตรียมเปิดใช้งานจริง

ขั้นตอนและค่าของชุด Production ปัจจุบันอยู่ที่ [DEPLOY_PRODUCTION.md](DEPLOY_PRODUCTION.md)
ต้องตั้ง SITE_URL และ REDIS_URL เพิ่มด้วย; render.yaml รวม Cron แล้ว ห้าม deploy งานซ้ำ

เอกสารนี้เก็บขั้นตอนสำหรับผู้ดูแลระบบ ไม่แสดงเป็นคำอธิบายบนหน้าเว็บลูกค้า

## 1. บัญชีบริการภายนอก

- สร้าง PostgreSQL สำหรับข้อมูลหลัก ห้ามใช้ SQLite บน Production
- สร้าง Cloudinary และกำหนด CLOUDINARY_URL
- เปิด Stripe Live mode, Stripe Checkout และ Stripe Connect Express
- สร้าง SMTP สำหรับอีเมลยืนยันบัญชี รหัส MFA และแจ้งเตือน
- สร้างโครงการ Sentry แล้วกำหนด SENTRY_DSN
- จดโดเมนและชี้ DNS มาที่ Render จากนั้นเพิ่มโดเมนใน ALLOWED_HOSTS และ CSRF_TRUSTED_ORIGINS

## 2. ตัวแปรสำคัญบน Render

กรอกตัวแปรที่ตั้งเป็น sync: false ใน render.yaml ให้ครบ โดยเฉพาะ:

- CSRF_TRUSTED_ORIGINS=https://ชื่อโดเมนจริง
- CLOUDINARY_URL
- STRIPE_SECRET_KEY
- STRIPE_PUBLISHABLE_KEY
- STRIPE_WEBHOOK_SECRET
- EMAIL_HOST, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD
- DEFAULT_FROM_EMAIL, CONTACT_EMAIL
- SENTRY_DSN

อย่าใส่ secret จริงลง Git หรือไฟล์ .env.example

## 3. Stripe และการโอนเงินผู้ขาย

ตั้ง Webhook เป็น:

    https://ชื่อโดเมนจริง/payments/stripe/webhook/

เปิด event อย่างน้อย:

- checkout.session.completed
- checkout.session.expired
- payment_intent.payment_failed
- refund.created
- refund.updated
- account.updated

ทดสอบด้วย Test mode ให้ครบทั้งชำระสำเร็จ, webhook ซ้ำ, คืนเงิน และบัญชีผู้ขายรับเงิน ก่อนเปลี่ยน STRIPE_CONNECT_TRANSFERS_ENABLED=True

ระบบหักค่าธรรมเนียมตาม PLATFORM_FEE_PERCENT และพักยอดตาม SETTLEMENT_HOLD_DAYS การส่งเงินจริงใช้ Stripe idempotency key เพื่อป้องกันรายการซ้ำ

## 4. เอกสารส่วนตัว

เอกสารยืนยันเกษตรกร หลักฐานรายงาน และไฟล์แนบถูกเก็บใน private storage หากมีไฟล์เดิม ให้รันครั้งแรกโดยยังไม่ลบต้นฉบับ:

    python manage.py migrate_private_files

ตรวจว่าเจ้าของเอกสาร เจ้าหน้าที่ชุมชนที่เกี่ยวข้อง และเจ้าของระบบดาวน์โหลดได้ แล้วจึงรัน:

    python manage.py migrate_private_files --delete-public

## 5. งานอัตโนมัติ

คำสั่งเดียวดูแลออเดอร์หมดอายุ สต็อกต่ำ อีเมลค้าง ยอดผู้ขาย และล้าง log เก่า:

    python manage.py run_maintenance

ไฟล์ render.cron.yaml เป็น Blueprint แยกสำหรับ Cron Job ทุก 5 นาที เนื่องจาก Render Cron มีค่าใช้จ่าย จึงไม่ถูกเปิดอัตโนมัติจาก render.yaml แผนฟรี

## 6. ตรวจระบบก่อนเปิด

    python manage.py check
    python manage.py makemigrations --check --dry-run
    python manage.py check --deploy
    python manage.py check_production
    python manage.py test

หลัง deploy:

- /health/ ต้องตอบ {"status": "ok"}
- /ready/ ต้องตอบสถานะ ready
- สมัครบัญชีและรับอีเมลยืนยันได้
- เจ้าของระบบต้องผ่านรหัส MFA ก่อนเข้า /admin/
- เจ้าหน้าที่เปิดได้เฉพาะข้อมูลในชุมชนตนเอง
- ทดสอบชำระเงินจริงจำนวนต่ำและคืนเงินจริง
- ตรวจว่า Sentry รับ error ทดสอบ และ SMTP ไม่มีอีเมลตีกลับ

## 7. สำรองและกู้คืน

- Production ควรใช้ PostgreSQL แผนที่มีการสำรองข้อมูลตามระยะเวลา
- เก็บสำเนา pg_dump แยกจาก Render อย่างน้อยวันละครั้ง
- เปิดนโยบายสำรอง asset ใน Cloudinary
- ทดสอบกู้คืนลงฐานข้อมูลแยกอย่างน้อยทุก 3 เดือน
- ห้ามถือว่าการมี backup เพียงอย่างเดียวเพียงพอจนกว่าจะทดสอบ restore สำเร็จ

## 8. สิ่งที่ต้องมีจากธุรกิจ

โค้ดไม่สามารถกำหนดแทนเจ้าของระบบได้ ต้องจัดทำและตรวจทานก่อนรับเงินจริง:

- ชื่อกิจการ เลขผู้เสียภาษี และบัญชีธนาคาร
- อัตราค่าธรรมเนียมและภาษี
- เงื่อนไขการใช้งาน นโยบายความเป็นส่วนตัว และนโยบายคืนเงินฉบับจริง
- SLA การตอบรายงาน ระยะเวลาคืนเงิน และช่องทางช่วยเหลือลูกค้า
- ข้อตกลงกับผู้ขายเรื่องการจัดส่ง สินค้าเสียหาย และการเรียกคืนสินค้า

## การตั้งค่าอีเมลบน Render แผนฟรี

Render แผนฟรีบล็อก SMTP พอร์ต 25, 465 และ 587 ให้ใช้ผู้ให้บริการที่รองรับ TLS พอร์ต 2525 เช่น SendGrid:

- EMAIL_HOST=smtp.sendgrid.net
- EMAIL_PORT=2525
- EMAIL_HOST_USER=apikey
- EMAIL_HOST_PASSWORD=SendGrid API key
- DEFAULT_FROM_EMAIL=อีเมลผู้ส่งที่ยืนยันแล้ว

## บัญชีเจ้าของระบบครั้งแรก

กำหนด INITIAL_OWNER_USERNAME, INITIAL_OWNER_EMAIL และ INITIAL_OWNER_PASSWORD ตอนสร้าง Blueprint ระบบจะสร้าง Owner เพียงครั้งเดียว หลัง deploy และเข้า Admin สำเร็จแล้ว ให้ลบตัวแปรทั้งสามออกจาก Render

# Deploy Production และเปิดบริการจริง

เอกสารนี้เป็นขั้นตอนสำหรับชุด Production ปัจจุบัน ใช้แทนขั้นตอนแผนฟรี/WSGI ในคู่มือเดิม
การเพิ่มไฟล์เหล่านี้ยังไม่ได้สร้างบริการบน Render และยังไม่ได้ส่งอีเมลหรือโอนเงินจริง

## สิ่งที่โค้ดรองรับ

- เว็บ ASGI ผ่าน Daphne พร้อม HTTP และ WebSocket
- PostgreSQL เก็บข้อมูลหลัก และ Redis กระจายข้อความ/แจ้งเตือนระหว่าง process
- Cron ทุก 2 นาที: หมดอายุคำสั่งซื้อ ส่งอีเมลที่ค้าง และประมวลผลยอดผู้ขายที่ถึงกำหนด
- แชทผู้ซื้อกับผู้ขาย และผู้ขายกับ Admin: ข้อความทันที, กำลังพิมพ์, อ่านแล้ว, โหลดประวัติ, reconnect และป้องกันส่งซ้ำด้วย client ID
- Admin ใช้ session แยกจากหน้าเว็บและต้องผ่าน MFA ก่อนเชื่อมแชท
- อีเมลลืมรหัสผ่าน/ยืนยันบัญชี/MFA ใช้ SMTP เดิม มีคิวลองส่งซ้ำและไม่ส่งรหัสที่หมดอายุ
- รับ webhook พัสดุที่ลงลายเซ็น ตรวจรายการซ้ำและลำดับเวลา แสดงประวัติในหน้าคำสั่งซื้อ

การแจ้งเตือนแชททำงานขณะเปิดหน้าเว็บอยู่ ยังไม่ใช่ Push notification เมื่อปิดเบราว์เซอร์
ไม่มีระบบโทรเสียง/วิดีโอหรือส่งไฟล์แนบในแชทรุ่นนี้

## Frontend build และ CI

หน้าเว็บใช้ Tailwind CSS ที่คอมไพล์ไว้ใน `static/css/tailwind.css` และไม่พึ่ง Play CDN ใน Production
เมื่อแก้ template หรือเพิ่ม Tailwind class ให้ใช้ Node.js 22 แล้วรัน:

    npm install
    npm run build:css

ต้อง commit ไฟล์ CSS ที่สร้างใหม่ด้วย เพราะ Render ใช้ไฟล์ที่อยู่ใน repository แล้วรัน `collectstatic`
GitHub Actions ใน `.github/workflows/ci.yml` จะสร้าง CSS ซ้ำและตรวจว่าไฟล์ตรงกับ source พร้อมรัน Django checks, ตรวจ migration และ test suite ทุกครั้งที่ push หรือเปิด pull request

## 1. เตรียมบัญชีและงบประมาณ

ใช้บัญชี Render, PostgreSQL, Redis, Cloudinary, Stripe Connect และ SMTP ของคุณ
เลือกผู้ให้บริการ SMTP และยืนยันโดเมนผู้ส่ง พร้อมตั้ง DNS ตามผู้ให้บริการ (SPF/DKIM/DMARC)

ไฟล์ render.yaml ใช้บริการแบบเสียเงิน: web, database, key value และ cron
ตรวจยอดค่าใช้จ่ายที่ Render แสดงก่อนกดสร้างบริการ ไม่ต้อง deploy render.cron.yaml ซ้ำ เพราะงานนี้รวมใน render.yaml แล้ว

ดูชนิดบริการและแผนที่รองรับใน [Render Blueprint reference](https://render.com/docs/blueprint-spec)

## 2. สร้าง Blueprint

1. รัน `npm run build:css` และ `python manage.py test` แล้วส่งโค้ด, CSS ที่ build แล้ว และ migration ขึ้น repository โดยไม่รวม .env, ฐานข้อมูล, private_media หรือ logs
2. Render > New > Blueprint แล้วเลือก repository และ branch
3. ตรวจชื่อบริการ agri-market, agri-market-db, agri-market-realtime และ agri-market-maintenance
4. กรอก environment variables ที่กำหนด sync: false โดยใช้ .env.production.example เป็นรายการอ้างอิง
5. SECRET_KEY, DATABASE_URL และ REDIS_URL จะเชื่อมผ่าน Blueprint ส่วนค่าบริการอื่นต้องมาจากบัญชีของคุณ
6. ก่อนมีโดเมนส่วนตัว ใช้ URL onrender.com ของบริการเป็น SITE_URL และระบุ hostname จริงใน ALLOWED_HOSTS พร้อม URL https ใน CSRF_TRUSTED_ORIGINS
7. Deploy: build ติดตั้ง package และ collectstatic; pre-deploy ตรวจค่า migrate และสร้างเจ้าของระบบครั้งแรก; start ใช้ Daphne

ห้ามตั้ง ALLOWED_HOSTS เป็น * หรือ .onrender.com แบบครอบคลุมทั้งหมด
ใช้ SECRET_KEY เดียวกันระหว่างเว็บและ Cron ตามการอ้างอิงใน Blueprint

INITIAL_OWNER_USERNAME, INITIAL_OWNER_EMAIL, INITIAL_OWNER_PASSWORD ใช้สร้างบัญชีครั้งแรกเท่านั้น
หลังสร้างแล้วให้ลบ INITIAL_OWNER_PASSWORD ออกจาก environment และทดสอบ MFA

## 3. ตรวจอีเมลก่อนเปิดสมัครสมาชิก

ตั้ง EMAIL_HOST/PORT/USER/PASSWORD จากผู้ให้บริการ ไม่ใช้รหัสผ่านเข้าสู่เว็บทั่วไป
ใช้ TLS (ปกติ port 587) หรือ SSL (ปกติ 465) เพียงอย่างเดียว
ตั้ง DEFAULT_FROM_EMAIL ให้เป็นผู้ส่งที่ผู้ให้บริการอนุญาต

รันบน Render Shell:

    python manage.py check_production
    python manage.py check_email

คำสั่ง check_email ตรวจการเชื่อมต่อและยืนยันตัวตน SMTP แต่ไม่ส่งอีเมล
หากต้องการส่งถึงอีเมลของคุณเอง ให้ระบุปลายทางอย่างชัดเจน:

    python manage.py check_email --to your-address@example.com

จากนั้นทดสอบสมัครสมาชิก, ลิงก์ยืนยัน, ลืมรหัสผ่าน และ MFA จากกล่องจดหมายจริง
ตรวจทั้ง inbox และ spam รวมถึงลิงก์ต้องชี้ไป SITE_URL ไม่ใช่ localhost
ตรวจคิวที่ Admin > อีเมลที่ระบบส่ง เมื่อเปลี่ยน SMTP ให้ลองส่งรายการที่ล้มเหลวอีกครั้ง
รหัส MFA/ลิงก์ที่หมดอายุจะไม่ถูกนำกลับมาส่ง แม้กดลองอีกครั้ง

การเชื่อมผู้ให้บริการใหม่ผ่าน HTTP เช่น Resend ยังไม่ได้เปิดใช้ ต้องอนุญาตก่อนส่งข้อมูลบัญชี/รหัสไปยังบริการใหม่

## 4. Stripe และการโอนผู้ขาย

โปรเจกต์นี้ตั้ง `PAYMENT_MODE=test` เป็นค่าเริ่มต้น: หน้าชำระเงินและสถานะคำสั่งซื้อทำงานเหมือนจริง แต่จะไม่ตัดหรือโอนเงินจริง ระบบจะปฏิเสธ `sk_live_...` หากค่านี้ยังเป็น `test` หากตั้ง Stripe Test key ระบบจะใช้หน้า Stripe Test mode; หากไม่ตั้งคีย์ ระบบจะใช้หน้าชำระเงินจำลองภายในแทน

1. สร้างหรือเปิด Stripe Dashboard ใน Test mode แล้วนำเฉพาะ `sk_test_...`, `pk_test_...` และ webhook signing secret ของ Test mode มาใส่ใน environment
2. ใช้บัตรทดสอบ `4242 4242 4242 4242`, วันหมดอายุในอนาคต และ CVC สามหลัก เพื่อทดสอบรายการสำเร็จ
3. ใช้บัตร `4000 0000 0000 9995` เพื่อทดสอบกรณีถูกปฏิเสธ
4. คง `STRIPE_CONNECT_TRANSFERS_ENABLED=False` ไว้ระหว่างทำเดโม เพื่อไม่ให้ระบบสร้าง transfer แม้ในบัญชีทดสอบ

เมื่อจะรับเงินจริงในอนาคต ให้เปลี่ยน `PAYMENT_MODE=live` พร้อมแทนที่คีย์และ webhook secret ทุกตัวด้วยค่า Live mode หลังทดสอบครบแล้วเท่านั้น

ตั้ง webhook URL:

    https://your-domain/payments/stripe/webhook/

ตั้ง signing secret ให้ตรง endpoint และ mode นั้น พร้อมเปิด events ที่ระบบรองรับ
สำหรับ account.updated ให้สร้าง endpoint แยก เลือก events จาก connected accounts:

    https://your-domain/payments/stripe/connect/webhook/

นำ signing secret ของ endpoint นี้ใส่ STRIPE_CONNECT_WEBHOOK_SECRET ห้ามใช้ secret ของ Checkout endpoint แทน
endpoint นี้รับเฉพาะ account.updated และต้องมีลายเซ็นแม้ในโหมดพัฒนา
ดู [Stripe Connect webhooks](https://docs.stripe.com/connect/webhooks)

ผู้ขายเชื่อมบัญชีที่:

    /payments/connect/start/

ผู้ขายต้องกรอกข้อมูล Stripe Connect และบัญชีธนาคารให้ผ่านข้อกำหนดของ Stripe
เมื่อผู้ขายกลับมาหรือมี account.updated ระบบจึงอัปเดตความพร้อมรับเงิน

เปิด STRIPE_CONNECT_TRANSFERS_ENABLED=True บนเว็บเมื่อผ่านการทดสอบแล้ว
Cron ใช้ค่านี้จากเว็บ ตรวจว่าการเปลี่ยน environment มีผลกับงาน Cron ด้วย

เงื่อนไขก่อนโอน:
- ชำระเงินสำเร็จและคำสั่งซื้อเป็น completed
- ครบ SETTLEMENT_HOLD_DAYS ซึ่งนับจากเวลาปรับปรุง payment ตามตรรกะเดิม
- ไม่มีคำขอคืนเงินที่รอตรวจ/กำลังคืน/ล้มเหลวค้างอยู่
- บัญชี Stripe Connect พร้อมรับเงิน และยอด/สกุลเงิน/ผู้รับตรงกับรายการ
- ไม่ใช่รายการที่ Admin พักไว้ตรวจสอบ

ระบบตรวจ transfer เดิมก่อนสร้างใหม่ ใช้ idempotency key และลองซ้ำแบบเว้นระยะ
เมื่อเกิน SETTLEMENT_MAX_ATTEMPTS จะหยุดให้ผู้ดูแลตรวจ ไม่ลองไม่จำกัด
หากพบ transfer เดิมแต่รายละเอียดไม่ตรง จะเก็บรหัสและพักยอด ห้ามกดโอนใหม่โดยไม่ตรวจ Stripe

สำคัญ: Transfer นี้ย้ายยอดจากแพลตฟอร์มไปบัญชี Stripe Connect ของผู้ขาย
เงินเข้าธนาคารจริงขึ้นกับ payout schedule และความพร้อมบัญชีที่ Stripe จัดการ ไม่ใช่การโอนธนาคารทันทีโดยโค้ดนี้
ตรวจความพร้อมของ Connect ในประเทศ/บัญชีของคุณกับ Stripe ก่อนเปิดเงินจริง

อ้างอิง [Stripe transfers](https://docs.stripe.com/api/transfers/create) และ [รายการ transfer](https://docs.stripe.com/api/transfers/list)

## 5. ติดตามพัสดุ

เมื่อตั้ง `AFTERSHIP_API_KEY` ระบบจะส่งเลขพัสดุของคำสั่งซื้อที่ผู้ขายเปลี่ยนเป็น “จัดส่งแล้ว” ไปลงทะเบียนกับ AfterShip อัตโนมัติ โดยส่งเฉพาะเลขพัสดุ ชื่อออเดอร์ และเลขอ้างอิงคำสั่งซื้อ ไม่มีข้อมูลส่วนตัวผู้ซื้อ

เมื่อตั้งค่า AfterShip:
1. ตั้ง AFTERSHIP_API_KEY และ AFTERSHIP_WEBHOOK_SECRET ให้ตรงบัญชีผู้ให้บริการ
2. ตั้ง webhook URL https://your-domain/orders/tracking/aftership/webhook/
3. ส่ง tracking_update ทดสอบที่มี event_id, msg.id, msg.order_id, msg.tracking_number, msg.updated_at และ header aftership-hmac-sha256
4. ตรวจหน้าคำสั่งซื้อว่ามีสถานะและประวัติการเคลื่อนย้าย

Webhook ไม่รับข้อมูลที่ไม่ลงลายเซ็น ไม่เปลี่ยนคำสั่งซื้อเป็น completed และไม่ปล่อยยอดผู้ขายเพียงเพราะขนส่งแจ้ง Delivered
ยังต้องยืนยันรับสินค้าตามระบบคำสั่งซื้อเดิม

อ้างอิง [AfterShip webhook signature](https://www.aftership.com/docs/tracking/webhook/webhook-signature)

## 6. โดเมนและตรวจหลัง Deploy

- เพิ่ม custom domain ใน Render แล้วตั้ง DNS ตามค่าที่หน้า Render แสดง
- รอ HTTPS พร้อม แล้วเปลี่ยน SITE_URL, ALLOWED_HOSTS และ CSRF_TRUSTED_ORIGINS
- อัปเดต webhook URL ใน Stripe และผู้ให้บริการพัสดุ
- ตรวจ /ready/ ต้องตอบ 200; หาก database/migrations/Redis ไม่พร้อม จะตอบ 503
- เปิดสองเบราว์เซอร์คนละบัญชี: ผู้ขายส่งข้อความและ Admin ได้ badge โดยไม่รีเฟรช จากนั้นตอบกลับ
- ทดสอบตัด/ต่อเน็ต โหลดหน้าใหม่ และออกจากระบบว่า socket เก่าใช้ต่อไม่ได้
- ตรวจ Cron logs ว่าทำงานทุก 2 นาที ไม่ใช่เพียง deploy เว็บผ่าน
- ตั้ง monitoring/alert และ backup PostgreSQL; ทดลอง restore ในฐานแยกก่อนเปิดให้ลูกค้าจริง
- ทดสอบอัปโหลดรูปและเอกสารส่วนตัวบน Cloudinary พร้อมตรวจสิทธิ์เข้าถึง
- ยืนยันว่าการทดสอบ Stripe, SMTP และพัสดุผ่านจากบริการจริงก่อนประกาศพร้อมใช้งาน

## การทดสอบในเครื่อง

    python manage.py test --noinput
    python manage.py makemigrations --check --dry-run

Browser test แบบแยกฐานข้อมูล (ต้องติดตั้ง playwright และมี Microsoft Edge):

    python manage.py test accounts.test_browser_chat --settings=agri_market.browser_test_settings --noinput

ภาพผลทดสอบอยู่ใน .artifacts/ ซึ่งไม่ถูก commit
ห้ามใช้ browser_test_settings บน Production

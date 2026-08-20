"""Thai presentation labels used by Django Admin.

The database and API field names remain unchanged. Only model metadata rendered by
the management interface is localized here.
"""

from django.apps import apps


ADMIN_FIELD_LABELS = {
    "accounts.User": {
        "role": "สิทธิ์ผู้ใช้งาน",
        "display_name": "ชื่อที่แสดง",
        "phone": "หมายเลขโทรศัพท์",
        "email_verified_at": "วันที่ยืนยันอีเมล",
        "terms_accepted_at": "วันที่ยอมรับเงื่อนไข",
        "privacy_accepted_at": "วันที่ยอมรับนโยบายความเป็นส่วนตัว",
        "terms_version": "รุ่นของเงื่อนไขการใช้งาน",
        "privacy_version": "รุ่นของนโยบายความเป็นส่วนตัว",
    },
    "accounts.DeliveryAddress": {
        "user": "ผู้ใช้",
        "created_at": "วันที่สร้าง",
        "updated_at": "วันที่แก้ไขล่าสุด",
    },
    "payments.CustomerPaymentProfile": {
        "user": "ผู้ใช้",
        "stripe_customer_id": "รหัสลูกค้าในระบบชำระเงิน",
        "created_at": "วันที่สร้าง",
        "updated_at": "วันที่แก้ไขล่าสุด",
    },
    "payments.SavedPaymentMethod": {
        "profile": "บัญชีชำระเงิน",
        "stripe_payment_method_id": "รหัสวิธีชำระเงิน",
        "method_type": "ประเภทวิธีชำระเงิน",
        "brand": "ประเภทบัตร",
        "last4": "เลขท้ายบัตร 4 หลัก",
        "exp_month": "เดือนหมดอายุ",
        "exp_year": "ปีหมดอายุ",
        "is_default": "บัตรเริ่มต้น",
        "created_at": "วันที่บันทึก",
    },    "accounts.Community": {
        "slug": "ชื่อย่อสำหรับลิงก์",
    },
    "accounts.AuditEvent": {
        "actor": "ผู้ดำเนินการ",
        "action": "การดำเนินการ",
        "target_type": "ประเภทข้อมูล",
        "target_id": "รหัสข้อมูล",
        "description": "รายละเอียด",
        "before": "ข้อมูลก่อนแก้ไข",
        "after": "ข้อมูลหลังแก้ไข",
        "ip_address": "หมายเลขไอพี",
        "community": "ชุมชน/สหกรณ์",
        "created_at": "วันที่ดำเนินการ",
    },
    "accounts.FarmerProfile": {
        "user": "บัญชีผู้ขาย",
        "community": "ชุมชน/สหกรณ์",
        "farm_name": "ชื่อฟาร์ม/ร้านค้า",
        "bio": "ข้อมูลฟาร์ม",
        "document_type": "ประเภทเอกสารยืนยัน",
        "verification_document": "เอกสารยืนยัน",
        "province": "จังหวัด",
        "verification_status": "สถานะการตรวจสอบ",
        "verified_by": "ตรวจสอบโดย",
        "verified_at": "วันที่ตรวจสอบ",
        "rejection_reason": "เหตุผลที่ไม่อนุมัติ",
    },
    "accounts.LoginAttempt": {
        "identifier_hash": "รหัสอ้างอิงบัญชี",
        "ip_hash": "รหัสอ้างอิงเครือข่าย",
        "failed_attempts": "จำนวนครั้งที่เข้าสู่ระบบไม่สำเร็จ",
        "blocked_until": "ระงับถึงวันที่",
        "updated_at": "วันที่ปรับปรุงล่าสุด",
    },
    "accounts.EmailDelivery": {
        "user": "บัญชีผู้รับ",
        "to_email": "อีเมลผู้รับ",
        "subject": "หัวข้ออีเมล",
        "body": "เนื้อหาอีเมล",
        "status": "สถานะการส่ง",
        "attempts": "จำนวนครั้งที่ส่ง",
        "last_error": "ข้อผิดพลาดล่าสุด",
        "next_attempt_at": "เวลาที่จะส่งซ้ำ",
        "sent_at": "วันที่ส่งสำเร็จ",
        "created_at": "วันที่สร้าง",
        "updated_at": "วันที่แก้ไขล่าสุด",
    },
    "accounts.Notification": {
        "user": "ผู้รับ",
        "title": "หัวข้อ",
        "message": "ข้อความ",
        "link": "ลิงก์ที่เกี่ยวข้อง",
        "is_read": "อ่านแล้ว",
    },
    "accounts.NewsPost": {
        "title": "หัวข้อข่าว",
        "slug": "ชื่อย่อสำหรับลิงก์",
        "summary": "สรุปข่าว",
        "body": "เนื้อหาข่าว",
        "audience": "กลุ่มผู้อ่าน",
        "is_published": "เผยแพร่แล้ว",
        "published_at": "วันและเวลาเผยแพร่",
        "created_by": "สร้างโดย",
    },
    "accounts.Report": {
        "reporter": "ผู้แจ้งรายงาน",
        "target_type": "ประเภทรายการที่ถูกรายงาน",
        "product": "สินค้า",
        "reported_user": "สมาชิกที่ถูกรายงาน",
        "order": "คำสั่งซื้อ",
        "community": "ชุมชน/สหกรณ์",
        "reason": "เหตุผลที่รายงาน",
        "details": "รายละเอียดปัญหา",
        "evidence": "หลักฐานประกอบ",
        "status": "สถานะการจัดการ",
        "handled_by": "ผู้รับผิดชอบ",
        "handled_at": "วันที่ดำเนินการ",
        "resolution_note": "บันทึกผลการดำเนินการ",
    },
    "accounts.ReportMessage": {
        "report": "รายงานปัญหา",
        "sender": "ผู้ส่งข้อความ",
        "message": "ข้อความ",
        "attachment": "ไฟล์แนบ",
        "created_at": "วันที่ส่ง",
    },
    "accounts.CommunityStaffProfile": {
        "user": "บัญชีเจ้าหน้าที่",
        "community": "ชุมชน/สหกรณ์ที่ดูแล",
        "title": "ตำแหน่ง",
    },
    "catalog.ProductReview": {
        "product": "สินค้า",
        "user": "ผู้รีวิว",
        "rating": "คะแนน",
        "comment": "ความคิดเห็น",
        "created_at": "วันที่รีวิว",
    },
    "catalog.Category": {
        "name": "ชื่อหมวดสินค้า",
        "slug": "ชื่อย่อสำหรับลิงก์",
        "description": "รายละเอียด",
        "is_active": "เปิดใช้งาน",
    },
    "catalog.Product": {
        "seller": "ผู้ขาย",
        "community": "ชุมชน/สหกรณ์",
        "category": "หมวดสินค้า",
        "name": "ชื่อสินค้า",
        "sku": "รหัสสินค้า",
        "description": "รายละเอียดสินค้า",
        "unit": "หน่วยขาย",
        "price": "ราคา",
        "stock_quantity": "จำนวนคงเหลือ",
        "minimum_order_quantity": "จำนวนสั่งซื้อขั้นต่ำ",
        "low_stock_threshold": "จุดแจ้งเตือนสินค้าใกล้หมด",
        "last_low_stock_notified_at": "วันที่แจ้งสินค้าใกล้หมดล่าสุด",
        "weight_grams": "น้ำหนักต่อหน่วย (กรัม)",
        "image": "รูปภาพหลัก",
        "harvest_date": "วันที่เก็บเกี่ยว",
        "expiry_date": "วันหมดอายุ",
        "status": "สถานะสินค้า",
        "rejection_reason": "เหตุผลที่ไม่อนุมัติ/บล็อก",
        "approved_by": "ตรวจสอบโดย",
        "approved_at": "วันที่ตรวจสอบ",
        "created_at": "วันที่เพิ่มสินค้า",
        "updated_at": "วันที่แก้ไขล่าสุด",
    },
    "catalog.ProductImage": {
        "product": "สินค้า",
        "image": "รูปภาพ",
        "alt_text": "คำอธิบายรูปภาพ",
        "sort_order": "ลำดับการแสดง",
        "created_at": "วันที่เพิ่ม",
    },
    "catalog.StockMovement": {
        "product": "สินค้า",
        "order": "คำสั่งซื้อ",
        "movement_type": "ประเภทรายการสต็อก",
        "quantity_change": "จำนวนที่เปลี่ยนแปลง",
        "balance_after": "คงเหลือหลังรายการ",
        "note": "หมายเหตุ",
        "created_at": "วันที่ทำรายการ",
    },
    "catalog.ProductFavorite": {
        "user": "ผู้ใช้งาน",
        "product": "สินค้า",
        "created_at": "วันที่กดถูกใจ",
    },
    "catalog.SellerFavorite": {
        "user": "ผู้ใช้งาน",
        "seller": "ผู้ขาย",
        "created_at": "วันที่กดถูกใจ",
    },
    "orders.Coupon": {"created_at": "วันที่สร้าง"},
    "orders.Order": {
        "reference": "เลขที่คำสั่งซื้อ",
        "buyer": "ผู้ซื้อ",
        "seller": "ผู้ขาย",
        "community": "ชุมชน/สหกรณ์",
        "coupon": "รหัสส่วนลด",
        "coupon_code": "รหัสส่วนลดที่ใช้",
        "status": "สถานะคำสั่งซื้อ",
        "payment_status": "สถานะการชำระเงิน",
        "subtotal": "ยอดรวมสินค้า",
        "shipping_fee": "ค่าจัดส่ง",
        "discount_amount": "ส่วนลด",
        "total_amount": "ยอดสุทธิ",
        "shipping_name": "ชื่อผู้รับ",
        "shipping_phone": "เบอร์โทรผู้รับ",
        "shipping_address": "ที่อยู่จัดส่ง",
        "note": "หมายเหตุจากผู้ซื้อ",
        "expires_at": "กำหนดเวลาชำระเงิน",
        "stock_reserved": "จองสต็อกแล้ว",
        "stock_released_at": "วันที่คืนสต็อก",
        "shipping_carrier": "บริษัทขนส่ง",
        "tracking_number": "หมายเลขติดตามพัสดุ",
        "shipped_at": "วันที่จัดส่ง",
        "delivered_at": "วันที่ส่งสำเร็จ",
        "cancelled_at": "วันที่ยกเลิก",
        "created_at": "วันที่สั่งซื้อ",
        "updated_at": "วันที่แก้ไขล่าสุด",
    },
    "orders.CouponRedemption": {
        "coupon": "รหัสส่วนลด",
        "order": "คำสั่งซื้อ",
        "discount_amount": "มูลค่าส่วนลด",
        "active": "ยังใช้สิทธิ์อยู่",
        "created_at": "วันที่ใช้สิทธิ์",
        "released_at": "วันที่คืนสิทธิ์",
    },
    "orders.OrderItem": {
        "order": "คำสั่งซื้อ",
        "product": "สินค้า",
        "product_name": "ชื่อสินค้า ณ วันที่สั่งซื้อ",
        "unit": "หน่วยขาย",
        "quantity": "จำนวน",
        "unit_price": "ราคาต่อหน่วย",
    },
    "orders.OrderStatusHistory": {
        "order": "คำสั่งซื้อ",
        "status": "สถานะ",
        "note": "หมายเหตุ",
        "changed_by": "เปลี่ยนสถานะโดย",
        "created_at": "วันที่เปลี่ยนสถานะ",
    },
    "payments.Payment": {
        "order": "คำสั่งซื้อ",
        "provider": "ช่องทางชำระเงิน",
        "status": "สถานะการชำระเงิน",
        "amount": "จำนวนเงิน",
        "currency": "สกุลเงิน",
        "checkout_session_id": "รหัสเซสชันชำระเงิน",
        "checkout_attempt_id": "รหัสรอบการชำระเงิน",
        "checkout_url": "ลิงก์หน้าชำระเงิน",
        "checkout_expires_at": "เวลาหมดอายุหน้าชำระเงิน",
        "payment_intent_id": "รหัสรายการชำระเงิน",
        "raw_payload": "ข้อมูลตอบกลับจากระบบชำระเงิน",
        "refunded_amount": "จำนวนเงินที่คืนแล้ว",
        "created_at": "วันที่สร้างรายการ",
        "updated_at": "วันที่แก้ไขล่าสุด",
    },
    "payments.SellerPaymentAccount": {
        "seller": "ผู้ขาย",
        "stripe_account_id": "รหัสบัญชีรับเงิน",
        "status": "สถานะบัญชีรับเงิน",
        "country": "ประเทศ",
        "details_submitted": "ส่งข้อมูลบัญชีครบแล้ว",
        "charges_enabled": "รับชำระเงินได้",
        "payouts_enabled": "รับเงินโอนได้",
        "created_at": "วันที่สร้าง",
        "updated_at": "วันที่แก้ไขล่าสุด",
    },
    "payments.SellerSettlement": {
        "payment": "รายการชำระเงิน",
        "seller": "ผู้ขาย",
        "gross_amount": "ยอดขายก่อนหักค่าธรรมเนียม",
        "fee_rate": "อัตราค่าธรรมเนียม",
        "platform_fee": "ค่าธรรมเนียมระบบ",
        "net_amount": "ยอดสุทธิของผู้ขาย",
        "currency": "สกุลเงิน",
        "status": "สถานะการจ่ายเงิน",
        "stripe_transfer_id": "รหัสอ้างอิงการโอนเงิน",
        "available_at": "วันที่พร้อมโอน",
        "transferred_at": "วันที่โอนสำเร็จ",
        "failure_reason": "สาเหตุที่ไม่สำเร็จ",
        "created_at": "วันที่สร้าง",
        "updated_at": "วันที่แก้ไขล่าสุด",
    },
    "payments.StripeEvent": {
        "event_id": "รหัสอ้างอิงเหตุการณ์",
        "event_type": "ประเภทเหตุการณ์",
        "payload": "ข้อมูลเหตุการณ์",
        "processed": "ประมวลผลแล้ว",
        "error_message": "ข้อความข้อผิดพลาด",
        "received_at": "วันที่รับข้อมูล",
        "processed_at": "วันที่ประมวลผล",
    },
    "payments.Refund": {
        "payment": "รายการชำระเงิน",
        "amount": "จำนวนเงินคืน",
        "reason": "เหตุผลการคืนเงิน",
        "evidence": "หลักฐานประกอบ",
        "status": "สถานะการคืนเงิน",
        "stripe_refund_id": "รหัสอ้างอิงการคืนเงิน",
        "requested_by": "ผู้ขอคืนเงิน",
        "resolution_note": "ผลการพิจารณา",
        "handled_by": "ผู้พิจารณา",
        "handled_at": "วันที่พิจารณา",
        "created_at": "วันที่ขอคืนเงิน",
        "updated_at": "วันที่แก้ไขล่าสุด",
    },
}


ADMIN_MODEL_LABELS = {
    "payments.CustomerPaymentProfile": (
        "บัญชีชำระเงินของลูกค้า",
        "บัญชีชำระเงินของลูกค้า",
    ),
    "payments.StripeEvent": (
        "เหตุการณ์จากระบบชำระเงิน",
        "เหตุการณ์จากระบบชำระเงิน",
    ),
}

def apply_admin_thai_labels():
    """Apply labels and shared usability defaults after models are loaded."""
    from django.contrib import admin

    for model_label, labels in ADMIN_FIELD_LABELS.items():
        model = apps.get_model(model_label)
        for field_name, label in labels.items():
            model._meta.get_field(field_name).verbose_name = label

    for model_label, names in ADMIN_MODEL_LABELS.items():
        model = apps.get_model(model_label)
        model._meta.verbose_name, model._meta.verbose_name_plural = names


    admin.site.empty_value_display = "ไม่มีข้อมูล"
    for model_admin in admin.site._registry.values():
        model_admin.list_per_page = 30
        model_admin.list_max_show_all = 200
        model_admin.preserve_filters = True
        model_admin.save_on_top = True
        if model_admin.search_fields and not model_admin.search_help_text:
            model_admin.search_help_text = "ค้นหาจากชื่อ รหัส หรือข้อมูลที่เกี่ยวข้อง"

from __future__ import annotations

import html
import os
import sys
import zipfile
import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "agri_market.settings")

import django

django.setup()

from django.apps import apps


OUTPUT_DIR = Path(__file__).resolve().parent
MODEL_LABELS = [
    "accounts.User",
]

TABLE_DESCRIPTIONS = {
    "accounts_notification": "ข้อมูลการแจ้งเตือนของผู้ใช้งาน",
    "accounts_user": "ข้อมูลบัญชีผู้ใช้งาน",
    "catalog_category": "ข้อมูลหมวดหมู่สินค้า",
    "accounts_community": "ข้อมูลชุมชนหรือสหกรณ์ของผู้ขาย",
    "accounts_farmerprofile": "ข้อมูลโปรไฟล์ร้านค้าและการยืนยันตัวตนของผู้ขาย",
    "catalog_product": "ข้อมูลสินค้าเกษตรที่ประกาศขาย",
    "catalog_productvariant": "ข้อมูลตัวเลือกหรือรูปแบบย่อยของสินค้า",
    "accounts_supportticket": "ข้อมูลคำขอและปัญหาที่ผู้ขายแจ้งถึงผู้ดูแลระบบ",
    "orders_order": "ข้อมูลคำสั่งซื้อสินค้า",
    "orders_orderitem": "ข้อมูลรายการสินค้าในคำสั่งซื้อ",
    "payments_payment": "ข้อมูลการชำระเงินของคำสั่งซื้อ",
    "orders_shipment": "ข้อมูลการจัดส่งและติดตามพัสดุ",
}

FIELD_DESCRIPTIONS = {
    "id": "รหัสประจำรายการ",
    "password": "รหัสผ่านที่จัดเก็บแบบเข้ารหัส",
    "last_login": "วันและเวลาที่เข้าสู่ระบบล่าสุด",
    "is_superuser": "สถานะผู้ดูแลระบบระดับสูง",
    "username": "ชื่อผู้ใช้สำหรับเข้าสู่ระบบ",
    "first_name": "ชื่อ",
    "last_name": "นามสกุล",
    "email": "อีเมล",
    "is_staff": "สถานะการเข้าถึงส่วนผู้ดูแลระบบ",
    "is_active": "สถานะเปิดใช้งาน",
    "date_joined": "วันและเวลาที่สมัครสมาชิก",
    "avatar": "ไฟล์รูปโปรไฟล์",
    "birth_date": "วันเกิด",
    "gender": "เพศ",
    "role": "บทบาทของผู้ใช้ในระบบ",
    "display_name": "ชื่อที่ใช้แสดงในระบบหรือชื่อร้านค้า",
    "phone": "หมายเลขโทรศัพท์",
    "email_verified_at": "วันและเวลาที่ยืนยันอีเมล",
    "terms_accepted_at": "วันและเวลาที่ยอมรับข้อกำหนดการใช้งาน",
    "privacy_accepted_at": "วันและเวลาที่ยอมรับนโยบายความเป็นส่วนตัว",
    "terms_version": "เวอร์ชันข้อกำหนดการใช้งานที่ยอมรับ",
    "privacy_version": "เวอร์ชันนโยบายความเป็นส่วนตัวที่ยอมรับ",
    "title": "หัวข้อการแจ้งเตือน",
    "message": "รายละเอียดข้อความ",
    "link": "ลิงก์ไปยังหน้าที่เกี่ยวข้อง",
    "is_read": "สถานะการอ่านข้อความ",
    "name": "ชื่อรายการ",
    "slug": "ชื่อย่อสำหรับใช้ใน URL",
    "description": "รายละเอียด",
    "image": "ไฟล์รูปภาพ",
    "province": "จังหวัด",
    "district": "อำเภอหรือเขต",
    "address": "ที่อยู่",
    "farm_name": "ชื่อฟาร์มหรือชื่อร้านค้า",
    "bio": "รายละเอียดแนะนำผู้ขายหรือร้านค้า",
    "store_cover": "ไฟล์รูปปกหน้าร้าน",
    "document_type": "ประเภทเอกสารยืนยันตัวตน",
    "verification_document": "ไฟล์เอกสารยืนยันตัวตน",
    "verification_status": "สถานะการตรวจสอบผู้ขาย",
    "verified_at": "วันและเวลาที่ตรวจสอบสำเร็จ",
    "rejection_reason": "เหตุผลที่ไม่อนุมัติ",
    "sku": "รหัสสินค้า SKU",
    "unit": "หน่วยนับสินค้า",
    "price": "ราคาต่อหน่วย",
    "stock_quantity": "จำนวนสินค้าคงเหลือ",
    "minimum_order_quantity": "จำนวนสั่งซื้อขั้นต่ำ",
    "maximum_order_quantity": "จำนวนสั่งซื้อสูงสุดต่อคำสั่งซื้อ",
    "low_stock_threshold": "จำนวนคงเหลือที่ใช้แจ้งเตือนสินค้าใกล้หมด",
    "last_low_stock_notified_at": "วันและเวลาที่แจ้งเตือนสินค้าใกล้หมดล่าสุด",
    "weight_grams": "น้ำหนักพัสดุเป็นกรัม",
    "gtin": "รหัสสินค้า GTIN",
    "package_length_cm": "ความยาวพัสดุเป็นเซนติเมตร",
    "package_width_cm": "ความกว้างพัสดุเป็นเซนติเมตร",
    "package_height_cm": "ความสูงพัสดุเป็นเซนติเมตร",
    "preparation_days": "จำนวนวันที่ใช้เตรียมสินค้า",
    "size_chart_image": "ไฟล์รูปตารางขนาดสินค้า",
    "harvest_date": "วันที่เก็บเกี่ยว",
    "expiry_date": "วันหมดอายุ",
    "status": "สถานะรายการ",
    "approved_at": "วันและเวลาที่อนุมัติ",
    "sort_order": "ลำดับการแสดงผล",
    "category": "ประเภทหัวข้อปัญหา",
    "subject": "หัวข้อคำขอหรือปัญหา",
    "last_seller_message_at": "วันและเวลาข้อความล่าสุดจากผู้ขาย",
    "last_admin_message_at": "วันและเวลาข้อความล่าสุดจากผู้ดูแลระบบ",
    "admin_read_at": "วันและเวลาที่ผู้ดูแลระบบอ่านล่าสุด",
    "seller_read_at": "วันและเวลาที่ผู้ขายอ่านล่าสุด",
    "reference": "เลขอ้างอิงคำสั่งซื้อ",
    "coupon_code": "รหัสคูปองที่ใช้กับคำสั่งซื้อ",
    "payment_status": "สถานะการชำระเงิน",
    "subtotal": "ยอดรวมสินค้าก่อนค่าจัดส่งและส่วนลด",
    "shipping_fee": "ค่าจัดส่ง",
    "discount_amount": "มูลค่าส่วนลด",
    "total_amount": "ยอดชำระสุทธิ",
    "shipping_name": "ชื่อผู้รับสินค้า",
    "shipping_phone": "หมายเลขโทรศัพท์ผู้รับสินค้า",
    "shipping_address": "ที่อยู่จัดส่งสินค้า",
    "shipping_province": "จังหวัดที่จัดส่ง",
    "shipping_postal_code": "รหัสไปรษณีย์สำหรับจัดส่ง",
    "note": "หมายเหตุของคำสั่งซื้อ",
    "expires_at": "วันและเวลาที่คำสั่งซื้อหมดอายุ",
    "stock_reserved": "สถานะการจองสต็อกสินค้า",
    "stock_released_at": "วันและเวลาที่คืนสต็อกสินค้า",
    "shipping_carrier": "ชื่อบริษัทขนส่ง",
    "tracking_number": "หมายเลขติดตามพัสดุ",
    "shipped_at": "วันและเวลาที่จัดส่งสินค้า",
    "delivered_at": "วันและเวลาที่ส่งถึงผู้รับ",
    "received_confirmed_at": "วันและเวลาที่ผู้ซื้อยืนยันรับสินค้า",
    "cancelled_at": "วันและเวลาที่ยกเลิกคำสั่งซื้อ",
    "product_name": "ชื่อสินค้าที่บันทึก ณ เวลาสั่งซื้อ",
    "variant_name": "ชื่อตัวเลือกสินค้าที่บันทึก ณ เวลาสั่งซื้อ",
    "quantity": "จำนวนสินค้าที่สั่งซื้อ",
    "unit_price": "ราคาสินค้าต่อหน่วย ณ เวลาสั่งซื้อ",
    "provider": "ผู้ให้บริการชำระเงิน",
    "amount": "จำนวนเงินที่ชำระ",
    "currency": "สกุลเงิน",
    "checkout_session_id": "รหัสเซสชันสำหรับชำระเงิน",
    "checkout_attempt_id": "รหัสการพยายามสร้างรายการชำระเงิน",
    "checkout_url": "URL สำหรับดำเนินการชำระเงิน",
    "checkout_expires_at": "วันและเวลาที่ลิงก์ชำระเงินหมดอายุ",
    "payment_intent_id": "รหัสรายการชำระเงินจากผู้ให้บริการ",
    "raw_payload": "ข้อมูลดิบที่ได้รับจากผู้ให้บริการชำระเงิน",
    "refunded_amount": "จำนวนเงินที่คืนแล้ว",
    "carrier_slug": "รหัสย่อบริษัทขนส่ง",
    "provider_id": "รหัสรายการจากผู้ให้บริการขนส่ง",
    "checkpoints": "ประวัติสถานะการติดตามพัสดุ",
    "provider_updated_at": "วันและเวลาที่ผู้ให้บริการอัปเดตข้อมูลล่าสุด",
    "next_sync_at": "วันและเวลาที่กำหนดให้ซิงก์ข้อมูลครั้งถัดไป",
    "attempts": "จำนวนครั้งที่พยายามซิงก์ข้อมูล",
    "last_error": "ข้อความข้อผิดพลาดล่าสุด",
    "created_at": "วันและเวลาที่สร้างข้อมูล",
    "updated_at": "วันและเวลาที่แก้ไขข้อมูลล่าสุด",
}

TABLE_FIELD_DESCRIPTIONS = {
    ("accounts_notification", "user_id"): "รหัสผู้ใช้ที่ได้รับการแจ้งเตือน",
    ("accounts_notification", "sender_id"): "รหัสผู้ใช้ที่ส่งการแจ้งเตือน",
    ("accounts_notification", "product_id"): "รหัสสินค้าที่เกี่ยวข้องกับการแจ้งเตือน",
    ("accounts_farmerprofile", "user_id"): "รหัสบัญชีผู้ขาย",
    ("accounts_farmerprofile", "community_id"): "รหัสชุมชนหรือสหกรณ์ที่สังกัด",
    ("accounts_farmerprofile", "verified_by_id"): "รหัสผู้ดูแลระบบที่ตรวจสอบข้อมูล",
    ("catalog_product", "seller_id"): "รหัสผู้ขายเจ้าของสินค้า",
    ("catalog_product", "community_id"): "รหัสชุมชนหรือสหกรณ์เจ้าของสินค้า",
    ("catalog_product", "category_id"): "รหัสหมวดหมู่สินค้า",
    ("catalog_product", "approved_by_id"): "รหัสผู้ดูแลระบบที่อนุมัติสินค้า",
    ("catalog_productvariant", "product_id"): "รหัสสินค้าหลัก",
    ("catalog_productvariant", "name"): "ชื่อตัวเลือกสินค้า",
    ("accounts_supportticket", "seller_id"): "รหัสผู้ขายที่เปิดคำขอ",
    ("accounts_supportticket", "community_id"): "รหัสชุมชนหรือสหกรณ์ที่เกี่ยวข้อง",
    ("accounts_supportticket", "handled_by_id"): "รหัสผู้ดูแลระบบที่รับผิดชอบคำขอ",
    ("orders_order", "buyer_id"): "รหัสผู้ซื้อ",
    ("orders_order", "seller_id"): "รหัสผู้ขาย",
    ("orders_order", "community_id"): "รหัสชุมชนหรือสหกรณ์ของผู้ขาย",
    ("orders_order", "coupon_id"): "รหัสคูปองส่วนลด",
    ("orders_orderitem", "order_id"): "รหัสคำสั่งซื้อ",
    ("orders_orderitem", "product_id"): "รหัสสินค้า",
    ("orders_orderitem", "variant_id"): "รหัสตัวเลือกสินค้า",
    ("payments_payment", "order_id"): "รหัสคำสั่งซื้อที่ชำระเงิน",
    ("orders_shipment", "order_id"): "รหัสคำสั่งซื้อที่จัดส่ง",
}


def sql_type(field) -> str:
    field_type = field.get_internal_type()
    if field_type in {"BigAutoField", "BigIntegerField"}:
        return "BIGINT"
    if field_type in {"AutoField", "IntegerField", "PositiveIntegerField"}:
        return "INTEGER"
    if field_type in {"SmallIntegerField", "PositiveSmallIntegerField"}:
        return "SMALLINT"
    if field_type in {"CharField", "SlugField", "EmailField", "FileField", "ImageField"}:
        return f"VARCHAR({field.max_length})"
    if field_type == "TextField":
        return "TEXT"
    if field_type == "BooleanField":
        return "BOOLEAN"
    if field_type == "DateField":
        return "DATE"
    if field_type == "DateTimeField":
        return "DATETIME"
    if field_type == "DecimalField":
        return f"DECIMAL({field.max_digits},{field.decimal_places})"
    if field_type == "FloatField":
        return "FLOAT"
    if field_type == "UUIDField":
        return "UUID"
    if field_type == "JSONField":
        return "JSON"
    if field_type in {"ForeignKey", "OneToOneField"}:
        target = field.target_field
        return "BIGINT" if target.get_internal_type() == "BigAutoField" else "INTEGER"
    return field_type.replace("Field", "").upper()


def key_value(field) -> str:
    keys = []
    if field.primary_key:
        keys.append("PK")
    if field.is_relation and field.many_to_one or field.one_to_one:
        keys.append("FK")
    if field.unique and not field.primary_key:
        keys.append("UQ")
    return ", ".join(keys)


def reference_value(field) -> str:
    if not field.is_relation or not getattr(field, "remote_field", None):
        return ""
    target_model = field.remote_field.model
    return f"{target_model._meta.db_table}.{target_model._meta.pk.column}"


def field_description(table_name: str, field) -> str:
    description = TABLE_FIELD_DESCRIPTIONS.get((table_name, field.column))
    if not description:
        description = FIELD_DESCRIPTIONS.get(field.column)
    if not description:
        description = str(field.verbose_name).strip().capitalize()
    if field.null:
        description += " (อนุญาตให้ว่าง)"
    return description


def collect_tables():
    result = []
    for label in MODEL_LABELS:
        model = apps.get_model(label)
        table_name = model._meta.db_table
        rows = []
        for index, field in enumerate(model._meta.fields, start=1):
            rows.append(
                {
                    "index": str(index),
                    "name": field.column,
                    "type": sql_type(field),
                    "description": field_description(table_name, field),
                    "key": key_value(field),
                    "reference": reference_value(field),
                }
            )
        result.append(
            {
                "table": table_name,
                "description": TABLE_DESCRIPTIONS[table_name],
                "rows": rows,
            }
        )
    return result


def collect_accounts_user_from_database():
    database_path = PROJECT_ROOT / "db.sqlite3"
    with sqlite3.connect(database_path) as connection:
        cursor = connection.cursor()
        columns = list(cursor.execute("PRAGMA table_info(accounts_user)"))
        indexes = list(cursor.execute("PRAGMA index_list(accounts_user)"))

    unique_columns = {"username", "email"}
    rows = []
    for ordinal, column_name, column_type, not_null, _default, is_primary_key in columns:
        description = FIELD_DESCRIPTIONS.get(column_name, column_name.replace("_", " "))
        if column_name == "role":
            description = "บทบาทผู้ใช้: consumer, farmer, cooperative_staff หรือ owner"
        if not not_null:
            description += " (อนุญาตให้ว่าง)"
        key = "PK" if is_primary_key else "UQ" if column_name in unique_columns else ""
        rows.append(
            {
                "index": str(ordinal + 1),
                "name": column_name,
                "type": column_type.upper(),
                "description": description,
                "key": key,
                "reference": "",
            }
        )

    if not any(index[2] for index in indexes):
        raise RuntimeError("accounts_user is missing its expected unique indexes")
    return [
        {
            "table": "accounts_user",
            "description": "ข้อมูลบัญชีผู้ใช้จากตารางจริง accounts_user ในฐานข้อมูล db.sqlite3",
            "rows": rows,
        }
    ]


def render_database_url() -> str | None:
    value = os.environ.get("DATABASE_URL")
    if value:
        return value.strip().strip('"').strip("'")
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def postgres_type(data_type, char_length, precision, scale, udt_name) -> str:
    if data_type == "character varying":
        return f"VARCHAR({char_length})"
    if data_type == "numeric":
        return f"DECIMAL({precision},{scale})"
    if data_type == "timestamp with time zone":
        return "TIMESTAMPTZ"
    if data_type == "timestamp without time zone":
        return "TIMESTAMP"
    if data_type == "USER-DEFINED":
        return str(udt_name).upper()
    return str(data_type).upper()


def collect_accounts_user_from_render():
    database_url = render_database_url()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to inspect thin-dee-db")

    import psycopg2

    with psycopg2.connect(database_url, connect_timeout=15) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name, ordinal_position, data_type, character_maximum_length,
                       numeric_precision, numeric_scale, is_nullable, udt_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'accounts_user'
                ORDER BY ordinal_position
                """
            )
            columns = cursor.fetchall()
            cursor.execute(
                """
                SELECT kcu.column_name, tc.constraint_type,
                       ccu.table_name, ccu.column_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                LEFT JOIN information_schema.constraint_column_usage AS ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.table_schema = tc.table_schema
                WHERE tc.table_schema = 'public'
                  AND tc.table_name = 'accounts_user'
                  AND tc.constraint_type IN ('PRIMARY KEY', 'UNIQUE', 'FOREIGN KEY')
                """
            )
            constraints = cursor.fetchall()
            cursor.execute(
                """
                SELECT indexdef
                FROM pg_indexes
                WHERE schemaname = 'public' AND tablename = 'accounts_user'
                """
            )
            indexes = [row[0].lower() for row in cursor.fetchall()]

    if not columns:
        raise RuntimeError("Table public.accounts_user was not found in the connected database")

    keys_by_column = {}
    references = {}
    for column_name, constraint_type, referenced_table, referenced_column in constraints:
        label = {"PRIMARY KEY": "PK", "UNIQUE": "UQ", "FOREIGN KEY": "FK"}[constraint_type]
        keys_by_column.setdefault(column_name, set()).add(label)
        if constraint_type == "FOREIGN KEY" and referenced_table and referenced_column:
            references[column_name] = f"{referenced_table}.{referenced_column}"
    for index_definition in indexes:
        if "unique" in index_definition and "email" in index_definition:
            keys_by_column.setdefault("email", set()).add("UQ")

    key_order = {"PK": 0, "FK": 1, "UQ": 2}
    rows = []
    for name, ordinal, data_type, char_length, precision, scale, nullable, udt_name in columns:
        description = FIELD_DESCRIPTIONS.get(name, name.replace("_", " "))
        if name == "role":
            description = "บทบาทผู้ใช้: consumer, farmer, cooperative_staff หรือ owner"
        if nullable == "YES":
            description += " (อนุญาตให้ว่าง)"
        rows.append(
            {
                "index": str(ordinal),
                "name": name,
                "type": postgres_type(data_type, char_length, precision, scale, udt_name),
                "description": description,
                "key": ", ".join(sorted(keys_by_column.get(name, set()), key=key_order.get)),
                "reference": references.get(name, ""),
            }
        )
    return [
        {
            "table": "accounts_user",
            "description": "ข้อมูลบัญชีผู้ใช้จากฐานข้อมูล PostgreSQL บน Render (thin-dee-db)",
            "rows": rows,
        }
    ]


def markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def write_markdown(tables, markdown_path: Path, account_label: str) -> None:
    lines = [
        "# 3.6 พจนานุกรมข้อมูล (Data Dictionary)",
        "",
        f"เอกสารนี้จัดทำจากโครงสร้างฐานข้อมูลของระบบ Thin Dee โดยแสดงชนิดข้อมูล คีย์ และตารางอ้างอิงของบัญชี{account_label}",
        "",
    ]
    for number, table in enumerate(tables, start=1):
        lines.extend(
            [
                f"## ตารางที่ 3.{number} ตารางข้อมูล `{table['table']}`",
                "",
                f"**คำอธิบาย:** {table['description']}",
                "",
                "| ลำดับ | ชื่อฟิลด์ | ชนิด | คำอธิบาย | Key | Reference |",
                "|---:|---|---|---|:---:|---|",
            ]
        )
        for row in table["rows"]:
            lines.append(
                "| " + " | ".join(markdown_cell(row[key]) for key in ("index", "name", "type", "description", "key", "reference")) + " |"
            )
        lines.append("")
    markdown_path.write_text("\n".join(lines), encoding="utf-8")


def xml_text(value: str) -> str:
    return html.escape(str(value), quote=False)


def run(text: str, *, bold: bool = False, size: int = 28, align: str | None = None) -> str:
    props = [
        '<w:rFonts w:ascii="TH Sarabun New" w:hAnsi="TH Sarabun New" w:eastAsia="TH Sarabun New" w:cs="TH Sarabun New"/>',
        f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>',
    ]
    if bold:
        props.append("<w:b/><w:bCs/>")
    paragraph_props = f'<w:pPr><w:jc w:val="{align}"/></w:pPr>' if align else ""
    return f'<w:p>{paragraph_props}<w:r><w:rPr>{"".join(props)}</w:rPr><w:t xml:space="preserve">{xml_text(text)}</w:t></w:r></w:p>'


def page_break() -> str:
    return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'


def table_cell(text: str, width: int, *, bold: bool = False, center: bool = False, shade: bool = False) -> str:
    tc_props = [f'<w:tcW w:w="{width}" w:type="dxa"/>', '<w:vAlign w:val="center"/>']
    if shade:
        tc_props.append('<w:shd w:val="clear" w:color="auto" w:fill="D9E1F2"/>')
    paragraph_props = '<w:pPr><w:jc w:val="center"/><w:spacing w:before="0" w:after="0"/></w:pPr>' if center else '<w:pPr><w:spacing w:before="0" w:after="0"/></w:pPr>'
    r_props = '<w:rFonts w:ascii="TH Sarabun New" w:hAnsi="TH Sarabun New" w:eastAsia="TH Sarabun New" w:cs="TH Sarabun New"/><w:sz w:val="24"/><w:szCs w:val="24"/>'
    if bold:
        r_props += "<w:b/><w:bCs/>"
    return f'<w:tc><w:tcPr>{"".join(tc_props)}</w:tcPr><w:p>{paragraph_props}<w:r><w:rPr>{r_props}</w:rPr><w:t xml:space="preserve">{xml_text(text)}</w:t></w:r></w:p></w:tc>'


def word_table(rows) -> str:
    widths = [600, 1650, 1350, 2600, 650, 1700]
    headers = ["ลำดับ", "ชื่อฟิลด์", "ชนิด", "คำอธิบาย", "Key", "Reference"]
    grid = "".join(f'<w:gridCol w:w="{width}"/>' for width in widths)
    border = '<w:top w:val="single" w:sz="6" w:color="666666"/><w:left w:val="single" w:sz="6" w:color="666666"/><w:bottom w:val="single" w:sz="6" w:color="666666"/><w:right w:val="single" w:sz="6" w:color="666666"/><w:insideH w:val="single" w:sz="4" w:color="999999"/><w:insideV w:val="single" w:sz="4" w:color="999999"/>'
    parts = [
        '<w:tbl><w:tblPr><w:tblW w:w="9550" w:type="dxa"/><w:tblLayout w:type="fixed"/>',
        f'<w:tblBorders>{border}</w:tblBorders>',
        '<w:tblCellMar><w:top w:w="80" w:type="dxa"/><w:left w:w="80" w:type="dxa"/><w:bottom w:w="80" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar></w:tblPr>',
        f"<w:tblGrid>{grid}</w:tblGrid>",
        '<w:tr><w:trPr><w:tblHeader w:val="true"/></w:trPr>',
    ]
    for header, width in zip(headers, widths):
        parts.append(table_cell(header, width, bold=True, center=True, shade=True))
    parts.append("</w:tr>")
    for row in rows:
        parts.append("<w:tr>")
        values = [row["index"], row["name"], row["type"], row["description"], row["key"], row["reference"]]
        for position, (value, width) in enumerate(zip(values, widths)):
            parts.append(table_cell(value, width, center=position in {0, 4}))
        parts.append("</w:tr>")
    parts.append("</w:tbl>")
    return "".join(parts)


def document_xml(tables, account_label: str) -> str:
    body = [run("3.6 พจนานุกรมข้อมูล (Data Dictionary)", bold=True, size=36)]
    body.append(run(f"พจนานุกรมข้อมูลบัญชี{account_label}ของระบบ Thin Dee จัดทำจากโครงสร้างฐานข้อมูลจริงของระบบ", size=28))
    for number, table in enumerate(tables, start=1):
        if number > 1:
            body.append(page_break())
        body.append(run(f"ตารางที่ 3.{number} ตารางข้อมูล {table['table']}", bold=True, size=30))
        body.append(run(f"คำอธิบาย : {table['description']}", size=28))
        body.append(word_table(table["rows"]))
    body.append(
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="850" w:bottom="1134" w:left="850" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>'
    )
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + "".join(body) + "</w:body></w:document>"


def write_docx(tables, docx_path: Path, account_label: str) -> None:
    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>'''
    root_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>'''
    document_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''
    styles = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="TH Sarabun New" w:hAnsi="TH Sarabun New" w:eastAsia="TH Sarabun New" w:cs="TH Sarabun New"/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr></w:rPrDefault></w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
</w:styles>'''
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    core = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>พจนานุกรมข้อมูลบัญชี{account_label}ระบบ Thin Dee</dc:title><dc:creator>Thin Dee</dc:creator><cp:lastModifiedBy>Codex</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>
</cp:coreProperties>'''
    app = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>Microsoft Office Word</Application></Properties>'''

    with zipfile.ZipFile(docx_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types.encode("utf-8"))
        archive.writestr("_rels/.rels", root_rels.encode("utf-8"))
        archive.writestr("word/document.xml", document_xml(tables, account_label).encode("utf-8"))
        archive.writestr("word/styles.xml", styles.encode("utf-8"))
        archive.writestr("word/_rels/document.xml.rels", document_rels.encode("utf-8"))
        archive.writestr("docProps/core.xml", core.encode("utf-8"))
        archive.writestr("docProps/app.xml", app.encode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an account Data Dictionary.")
    parser.add_argument(
        "account_type",
        choices=("seller", "buyer", "admin", "accounts_user", "render_accounts_user", "render_seller"),
    )
    parser.add_argument("--output-suffix", help="Optional output filename suffix without the DATA_DICTIONARY_ prefix.")
    args = parser.parse_args()
    account_label = {"seller": "ผู้ขาย", "buyer": "ผู้ซื้อ", "admin": "ผู้ดูแลระบบ", "accounts_user": "ผู้ใช้", "render_accounts_user": "ผู้ใช้", "render_seller": "ผู้ขาย"}[args.account_type]
    suffix = {"seller": "SELLER_ACCOUNT", "buyer": "BUYER_ACCOUNT", "admin": "ADMIN_ACCOUNT", "accounts_user": "ACCOUNTS_USER", "render_accounts_user": "ACCOUNTS_USER_RENDER", "render_seller": "SELLER_ACCOUNT_RENDER"}[args.account_type]
    if args.output_suffix:
        suffix = args.output_suffix
    account_scope = {
        "seller": "โดย role เป็น farmer (เกษตรกรชุมชน) และรายละเอียดร้านค้าอยู่ในตาราง accounts_farmerprofile",
        "buyer": "โดย role เป็น consumer (ผู้บริโภคทั่วไป); ผู้ใช้ role เป็น farmer สามารถซื้อสินค้าได้ด้วย",
        "admin": "โดย role เป็น owner หรือกำหนด is_superuser เป็น True",
        "accounts_user": "จาก schema ฐานข้อมูลจริง db.sqlite3",
        "render_accounts_user": "จาก schema ฐานข้อมูล PostgreSQL บน Render",
        "render_seller": "จาก schema ฐานข้อมูล PostgreSQL บน Render (thin-dee-db) โดยระเบียนผู้ขายระบุด้วย role = farmer",
    }[args.account_type]
    docx_path = OUTPUT_DIR / f"DATA_DICTIONARY_{suffix}.docx"
    markdown_path = OUTPUT_DIR / f"DATA_DICTIONARY_{suffix}.md"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.account_type == "accounts_user":
        tables = collect_accounts_user_from_database()
    elif args.account_type in {"render_accounts_user", "render_seller"}:
        tables = collect_accounts_user_from_render()
    else:
        tables = collect_tables()
    if args.account_type not in {"accounts_user", "render_accounts_user"}:
        tables[0]["description"] = f"ข้อมูลบัญชี{account_label} {account_scope}"
    write_markdown(tables, markdown_path, account_label)
    write_docx(tables, docx_path, account_label)
    field_count = sum(len(table["rows"]) for table in tables)
    print(f"Created {docx_path}")
    print(f"Created {markdown_path}")
    print(f"Tables: {len(tables)}, fields: {field_count}")


if __name__ == "__main__":
    main()

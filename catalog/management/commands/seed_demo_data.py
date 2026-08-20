import struct
import zlib
from base64 import b64decode
from decimal import Decimal
from hashlib import md5
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from accounts.models import Community, User
from catalog.models import Category, Product


class Command(BaseCommand):
    help = "Seed demo communities, categories, and products for the marketplace"

    def _generate_product_image(self, product_name, slug):
        output_dir = Path(settings.MEDIA_ROOT) / "products"
        output_dir.mkdir(parents=True, exist_ok=True)
        file_path = output_dir / f"{slug}.png"

        if file_path.exists():
            return file_path

        seed = int(md5(product_name.encode("utf-8")).hexdigest()[:8], 16)
        width, height = 800, 600
        pixels = bytearray(width * height * 3)

        for y in range(height):
            for x in range(width):
                r = (seed + x * 3 + y * 7) % 256
                g = (seed * 2 + x * 5 + y * 3) % 256
                b = (seed * 3 + x * 2 + y * 9) % 256
                idx = (y * width + x) * 3
                pixels[idx] = r
                pixels[idx + 1] = g
                pixels[idx + 2] = b

        png_bytes = self._create_png(pixels, width, height)
        file_path.write_bytes(png_bytes)
        return file_path

    def _create_png(self, pixels, width, height):
        def chunk(chunk_type, data):
            return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)

        raw = b"\x00" + zlib.compress(pixels, 9)
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")

    def handle(self, *args, **options):
        community, _ = Community.objects.get_or_create(
            slug="ban-tung-ya",
            defaults={
                "name": "ชุมชนบ้านทุ่งหญ้า",
                "province": "เชียงใหม่",
                "district": "หางดง",
                "address": "หมู่ 4 ต.หางดง",
                "description": "ชุมชนเกษตรกรที่ปลูกผักและผลไม้ตามฤดูกาล",
                "is_active": True,
            },
        )

        categories = [
            ("ผักสด", "vegetables", "ผักสดจากสวนในชุมชน"),
            ("ผลไม้", "fruits", "ผลไม้คุณภาพจากท้องถิ่น"),
            ("อาหารแปรรูป", "processed", "อาหารแปรรูปจากเกษตรกร"),
        ]
        for name, slug, description in categories:
            Category.objects.get_or_create(
                slug=slug,
                defaults={"name": name, "description": description, "is_active": True},
            )

        farmer_user, created = User.objects.get_or_create(
            username="farmer.demo",
            defaults={
                "display_name": "เกษตรกรตัวอย่าง",
                "email": "farmer@example.com",
                "phone": "0812345678",
                "role": User.Roles.FARMER,
                "is_active": True,
            },
        )
        if created:
            farmer_user.set_password("Farmer@1234")
            farmer_user.save()

        from accounts.models import FarmerProfile

        profile, _ = FarmerProfile.objects.get_or_create(
            user=farmer_user,
            defaults={
                "farm_name": "สวนทุ่งหญ้า",
                "community": community,
                "province": community.province,
                "district": community.district,
                "address": "หมู่ 4 ต.หางดง",
                "bio": "ปลูกผักและผลไม้คุณภาพตามหลักเกษตรกรรมยั่งยืน",
                "verification_status": FarmerProfile.VerificationStatus.VERIFIED,
                "verified_by": farmer_user,
            },
        )
        if profile.verification_status != FarmerProfile.VerificationStatus.VERIFIED:
            profile.verification_status = FarmerProfile.VerificationStatus.VERIFIED
            profile.verified_by = farmer_user
            profile.save(update_fields=["verification_status", "verified_by"])

        products = [
            {
                "name": "ผักกาดขาว",
                "slug": "pak-kad-khao",
                "description": "ผักกาดสดใหม่จากสวนในชุมชน ราคาดีสำหรับอาหารประจำวัน",
                "unit": Product.Unit.BUNDLE,
                "price": Decimal("35.00"),
                "stock_quantity": Decimal("120"),
                "category": Category.objects.get(slug="vegetables"),
                "status": Product.Status.ACTIVE,
            },
            {
                "name": "มะเขือเทศเชอร์รี่",
                "slug": "cherry-tomato",
                "description": "มะเขือเทศหวานนุ่มปลูกแบบปลอดสารพิษ",
                "unit": Product.Unit.KG,
                "price": Decimal("80.00"),
                "stock_quantity": Decimal("60"),
                "category": Category.objects.get(slug="vegetables"),
                "status": Product.Status.ACTIVE,
            },
            {
                "name": "พริกหวานสีเขียว",
                "slug": "green-bell-pepper",
                "description": "พริกหวานกรอบหวานจากสวนเกษตรกรในท้องถิ่น",
                "unit": Product.Unit.KG,
                "price": Decimal("72.00"),
                "stock_quantity": Decimal("55"),
                "category": Category.objects.get(slug="vegetables"),
                "status": Product.Status.ACTIVE,
            },
            {
                "name": "กะหล่ำปลี",
                "slug": "cabbage",
                "description": "กะหล่ำปลีสดใหม่ให้ความกรอบและอาหารอร่อย",
                "unit": Product.Unit.PIECE,
                "price": Decimal("28.00"),
                "stock_quantity": Decimal("90"),
                "category": Category.objects.get(slug="vegetables"),
                "status": Product.Status.ACTIVE,
            },
            {
                "name": "แตงกวา",
                "slug": "cucumber",
                "description": "แตงกวาสดจากสวนแบบปลอดสารพิษ",
                "unit": Product.Unit.KG,
                "price": Decimal("25.00"),
                "stock_quantity": Decimal("70"),
                "category": Category.objects.get(slug="vegetables"),
                "status": Product.Status.ACTIVE,
            },
            {
                "name": "ส้มโอคั้น",
                "slug": "pomelo",
                "description": "ส้มโอหวานฉ่ำจากสวนในจังหวัดเชียงใหม่",
                "unit": Product.Unit.KG,
                "price": Decimal("95.00"),
                "stock_quantity": Decimal("40"),
                "category": Category.objects.get(slug="fruits"),
                "status": Product.Status.ACTIVE,
            },
            {
                "name": "มะม่วงแก้ว",
                "slug": "mango-kaew",
                "description": "มะม่วงหอมหวานจากสวนเกษตรกรในภาคเหนือ",
                "unit": Product.Unit.KG,
                "price": Decimal("110.00"),
                "stock_quantity": Decimal("35"),
                "category": Category.objects.get(slug="fruits"),
                "status": Product.Status.ACTIVE,
            },
            {
                "name": "กล้วยหอม",
                "slug": "banana-hom",
                "description": "กล้วยหอมหวานนุ่มจากสวนท้องถิ่น",
                "unit": Product.Unit.BUNDLE,
                "price": Decimal("45.00"),
                "stock_quantity": Decimal("80"),
                "category": Category.objects.get(slug="fruits"),
                "status": Product.Status.ACTIVE,
            },
            {
                "name": "ฝรั่งไทย",
                "slug": "guava-thai",
                "description": "ฝรั่งหวานฉ่ำพร้อมรับประทานสดหรือแปรรูป",
                "unit": Product.Unit.KG,
                "price": Decimal("65.00"),
                "stock_quantity": Decimal("45"),
                "category": Category.objects.get(slug="fruits"),
                "status": Product.Status.ACTIVE,
            },
            {
                "name": "สัปปะรดภูแล",
                "slug": "pineapple-phu-lai",
                "description": "สัปปะรดหวานกรอบจากสวนในจังหวัดลำพูน",
                "unit": Product.Unit.PIECE,
                "price": Decimal("60.00"),
                "stock_quantity": Decimal("50"),
                "category": Category.objects.get(slug="fruits"),
                "status": Product.Status.ACTIVE,
            },
            {
                "name": "น้ำพริกปลากราย",
                "slug": "nam-prik-pla-kra-yi",
                "description": "น้ำพริกแปรรูปจากผลผลิตชุมชนพร้อมรับประทานง่าย",
                "unit": Product.Unit.PACK,
                "price": Decimal("55.00"),
                "stock_quantity": Decimal("30"),
                "category": Category.objects.get(slug="processed"),
                "status": Product.Status.ACTIVE,
            },
            {
                "name": "แยมสตรอว์เบอร์รี่",
                "slug": "strawberry-jam",
                "description": "แยมรสหวานหอมจากผลไม้สดในชุมชน",
                "unit": Product.Unit.PACK,
                "price": Decimal("70.00"),
                "stock_quantity": Decimal("24"),
                "category": Category.objects.get(slug="processed"),
                "status": Product.Status.ACTIVE,
            },
            {
                "name": "ผงชาเขียว",
                "slug": "green-tea-powder",
                "description": "ผงชาจากใบชาใหม่และอ่อนนุ่ม",
                "unit": Product.Unit.PACK,
                "price": Decimal("95.00"),
                "stock_quantity": Decimal("22"),
                "category": Category.objects.get(slug="processed"),
                "status": Product.Status.ACTIVE,
            },
            {
                "name": "ข้าวเหนียวหอมมะลิ",
                "slug": "jasmine-rice",
                "description": "ข้าวเหนียวหอมมะลิจากนาข้าวชุมชนคุณภาพดี",
                "unit": Product.Unit.KG,
                "price": Decimal("88.00"),
                "stock_quantity": Decimal("65"),
                "category": Category.objects.get(slug="processed"),
                "status": Product.Status.ACTIVE,
            },
            {
                "name": "น้ำผักปั่น",
                "slug": "fresh-vegetable-juice",
                "description": "น้ำผักปั่นสดแบบไม่เติมน้ำตาลจากสวน",
                "unit": Product.Unit.BOX,
                "price": Decimal("58.00"),
                "stock_quantity": Decimal("18"),
                "category": Category.objects.get(slug="processed"),
                "status": Product.Status.ACTIVE,
            },
            {
                "name": "พริกป่นหอม",
                "slug": "chili-powder",
                "description": "พริกป่นจากพริกสดคั้นหอมและเผ็ดกำลังดี",
                "unit": Product.Unit.PACK,
                "price": Decimal("48.00"),
                "stock_quantity": Decimal("40"),
                "category": Category.objects.get(slug="processed"),
                "status": Product.Status.ACTIVE,
            },
            {
                "name": "ผักชี",
                "slug": "coriander",
                "description": "ผักชีสดหอมใช้ปรุงอาหารได้หลากหลาย",
                "unit": Product.Unit.BUNDLE,
                "price": Decimal("20.00"),
                "stock_quantity": Decimal("60"),
                "category": Category.objects.get(slug="vegetables"),
                "status": Product.Status.ACTIVE,
            },
            {
                "name": "กระเทียม",
                "slug": "garlic",
                "description": "กระเทียมสดจากสวนเกษตรกรมีกลิ่นหอมและกลิ่นแรง",
                "unit": Product.Unit.KG,
                "price": Decimal("40.00"),
                "stock_quantity": Decimal("85"),
                "category": Category.objects.get(slug="vegetables"),
                "status": Product.Status.ACTIVE,
            },
            {
                "name": "หอมใหญ่",
                "slug": "shallot",
                "description": "หอมใหญ่สดขนาดพอดีใช้กับทุกเมนู",
                "unit": Product.Unit.KG,
                "price": Decimal("36.00"),
                "stock_quantity": Decimal("75"),
                "category": Category.objects.get(slug="vegetables"),
                "status": Product.Status.ACTIVE,
            },
            {
                "name": "เงาะเขียว",
                "slug": "rambutan",
                "description": "เงาะหวานฉ่ำพร้อมรับประทานสดในช่วงฤดู",
                "unit": Product.Unit.KG,
                "price": Decimal("85.00"),
                "stock_quantity": Decimal("30"),
                "category": Category.objects.get(slug="fruits"),
                "status": Product.Status.ACTIVE,
            },
        ]

        created_count = 0
        for payload in products:
            product, created = Product.objects.get_or_create(
                name=payload["name"],
                defaults={
                    "seller": farmer_user,
                    "community": community,
                    "category": payload["category"],
                    "description": payload["description"],
                    "unit": payload["unit"],
                    "price": payload["price"],
                    "stock_quantity": payload["stock_quantity"],
                    "status": payload["status"],
                },
            )
            if created:
                created_count += 1

            if not product.image:
                image_path = self._generate_product_image(payload["name"], payload["slug"])
                with image_path.open("rb") as image_file:
                    product.image.save(image_path.name, ContentFile(image_file.read()), save=True)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded demo community, categories, and {len(products)} products with images."
            )
        )

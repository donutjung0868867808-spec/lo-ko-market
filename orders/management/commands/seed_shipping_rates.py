from decimal import Decimal

from django.core.management.base import BaseCommand

from orders.models import ShippingRate


# Project defaults use whole-kilogram tiers: 39 baht for the first kilogram,
# with tier prices through 10kg, then 10 baht for every additional started kilogram. Administrators can adjust
# these values in the ShippingRate admin without this command overwriting them.
REGIONAL_RATES = (
    (("กรุงเทพมหานคร",), Decimal("39.00"),
        Decimal("10.00")),
    (("นนทบุรี", "ปทุมธานี", "สมุทรปราการ"), Decimal("39.00"),
        Decimal("10.00")),
    (
        (
            "อ่างทอง",
            "พระนครศรีอยุธยา",
            "ชัยนาท",
            "ลพบุรี",
            "สระบุรี",
            "สิงห์บุรี",
            "สุพรรณบุรี",
            "นครปฐม",
            "สมุทรสาคร",
            "สมุทรสงคราม",
            "กาญจนบุรี",
            "ราชบุรี",
            "เพชรบุรี",
            "ประจวบคีรีขันธ์",
        ),
        Decimal("39.00"),
        Decimal("10.00"),
    ),
    (
        (
            "จันทบุรี",
            "ฉะเชิงเทรา",
            "ชลบุรี",
            "ตราด",
            "ปราจีนบุรี",
            "ระยอง",
            "สระแก้ว",
            "นครนายก",
        ),
        Decimal("39.00"),
        Decimal("10.00"),
    ),
    (
        (
            "เชียงใหม่",
            "เชียงราย",
            "แม่ฮ่องสอน",
            "ลำพูน",
            "ลำปาง",
            "พะเยา",
            "แพร่",
            "น่าน",
            "อุตรดิตถ์",
            "พิษณุโลก",
            "พิจิตร",
            "เพชรบูรณ์",
            "สุโขทัย",
            "ตาก",
            "กำแพงเพชร",
            "นครสวรรค์",
            "อุทัยธานี",
        ),
        Decimal("39.00"),
        Decimal("10.00"),
    ),
    (
        (
            "กาฬสินธุ์",
            "ขอนแก่น",
            "ชัยภูมิ",
            "นครพนม",
            "นครราชสีมา",
            "บึงกาฬ",
            "บุรีรัมย์",
            "มหาสารคาม",
            "มุกดาหาร",
            "ยโสธร",
            "ร้อยเอ็ด",
            "เลย",
            "ศรีสะเกษ",
            "สกลนคร",
            "สุรินทร์",
            "หนองคาย",
            "หนองบัวลำภู",
            "อำนาจเจริญ",
            "อุดรธานี",
            "อุบลราชธานี",
        ),
        Decimal("39.00"),
        Decimal("10.00"),
    ),
    (
        (
            "กระบี่",
            "ชุมพร",
            "ตรัง",
            "นครศรีธรรมราช",
            "นราธิวาส",
            "ปัตตานี",
            "พังงา",
            "พัทลุง",
            "ภูเก็ต",
            "ระนอง",
            "สตูล",
            "สงขลา",
            "สุราษฎร์ธานี",
            "ยะลา",
        ),
        Decimal("39.00"),
        Decimal("10.00"),
    ),
)


class Command(BaseCommand):
    help = "Create default province shipping rates without changing existing rates."

    def handle(self, *args, **options):
        created = 0
        for provinces, base_fee, fee_per_kg in REGIONAL_RATES:
            for province in provinces:
                _, was_created = ShippingRate.objects.get_or_create(
                    province=province,
                    defaults={
                        "base_fee": base_fee,
                        "fee_per_kg": fee_per_kg,
                        "is_active": True,
                    },
                )
                created += was_created
        self.stdout.write(
            self.style.SUCCESS(
                f"Created {created} province shipping rates; existing rates were kept."
            )
        )

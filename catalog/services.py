from datetime import timedelta

from django.db import models, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from accounts.models import Notification, User
from accounts.services import notify_user

from .models import Product, ProductDetailImage, ProductImage, StockMovement


def create_pending_product(*, seller, community, product, gallery_images, detail_images, detail_image_size):
    """Create a pending product and all inventory/media records as one database transaction."""
    gallery_images = list(gallery_images)
    detail_images = list(detail_images)

    with transaction.atomic():
        if not product.image and gallery_images:
            product.image = gallery_images.pop(0)
        product.seller = seller
        product.community = community
        product.status = Product.Status.PENDING
        product.save()

        for index, image in enumerate(gallery_images, start=1):
            ProductImage.objects.create(
                product=product,
                image=image,
                sort_order=index,
            )
        for index, image in enumerate(detail_images, start=1):
            ProductDetailImage.objects.create(
                product=product,
                image=image,
                display_size=detail_image_size,
                sort_order=index,
            )
        StockMovement.objects.create(
            product=product,
            movement_type=StockMovement.MovementType.MANUAL,
            quantity_change=product.stock_quantity,
            balance_after=product.stock_quantity,
            note="สต็อกเริ่มต้นเมื่อเพิ่มสินค้า",
        )

        reviewers = User.objects.filter(is_active=True).filter(
            Q(
                role=User.Roles.COOPERATIVE_STAFF,
                community_staff_profile__community=community,
            )
            | Q(role=User.Roles.OWNER)
        ).distinct()
        Notification.objects.bulk_create(
            [
                Notification(
                    user=reviewer,
                    title="มีสินค้าใหม่รออนุมัติ",
                    message=f"{product.name} จาก {seller} รอการตรวจสอบ",
                    link=reverse("catalog:product_review"),
                )
                for reviewer in reviewers
            ]
        )

    return product


def notify_low_stock(product_id):
    product = Product.objects.select_related("seller").filter(pk=product_id).first()
    if not product or product.stock_quantity > product.low_stock_threshold:
        return False
    if (
        product.last_low_stock_notified_at
        and product.last_low_stock_notified_at > timezone.now() - timedelta(hours=24)
    ):
        return False

    product.last_low_stock_notified_at = timezone.now()
    product.save(update_fields=["last_low_stock_notified_at", "updated_at"])
    notify_user(
        product.seller,
        f"สินค้าใกล้หมด: {product.name}",
        f"เหลือ {product.stock_quantity} {product.get_unit_display()}",
        product.get_absolute_url(),
    )
    return True

def notify_low_stock_for_all():
    count = 0
    product_ids = Product.objects.filter(
        status=Product.Status.ACTIVE,
        stock_quantity__lte=models.F("low_stock_threshold"),
    ).values_list("id", flat=True)
    for product_id in product_ids:
        count += int(notify_low_stock(product_id))
    return count

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.management import call_command
from django.db import transaction
from django.db.models import Avg, Count, Max, Prefetch, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from accounts.decorators import role_required, user_community
from accounts.models import AuditEvent, Community, Notification, Report, User
from accounts.services import record_audit

from orders.models import Order

from accounts.forms import ReportForm
from .forms import ProductForm, ProductImageForm, ProductReviewForm
from .models import (
    Category,
    HomeSlide,
    Product,
    ProductClick,
    ProductDetailImage,
    ProductFavorite,
    ProductImage,
    ProductReview,
    ProductReviewMedia,
    SellerFavorite,
    SellerStoreVisit,
    StockMovement,
    review_media_type_for_upload,
)


def ensure_demo_catalog_data():
    if not settings.ENABLE_DEMO_DATA or Product.objects.exists():
        return
    call_command("seed_demo_data", verbosity=0)


def analytics_session_key(request):
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def track_store_visit(request, seller):
    if request.user.is_authenticated and request.user.pk == seller.pk:
        return
    SellerStoreVisit.objects.get_or_create(
        seller=seller,
        session_key=analytics_session_key(request),
        visited_on=timezone.localdate(),
    )


def track_product_click(request, product):
    if request.user.is_authenticated and request.user.pk == product.seller_id:
        return
    ProductClick.objects.create(
        seller=product.seller,
        product=product,
        session_key=analytics_session_key(request),
    )


def save_product_gallery_images(product, images):
    for image in images:
        ProductImage.objects.create(product=product, image=image)


def save_product_detail_images(product, images):
    next_sort_order = product.detail_images.aggregate(last=Max("sort_order"))["last"] or 0
    for image in images:
        next_sort_order += 1
        ProductDetailImage.objects.create(product=product, image=image, sort_order=next_sort_order)


def use_first_gallery_image_as_cover(product, images):
    images = list(images)
    if not product.image and images:
        product.image = images.pop(0)
    return images


def can_review_product(user, product):
    """Only customers with a successful, active purchase can review a product."""
    if not user.is_authenticated or product.seller_id == user.id:
        return False

    return Order.objects.filter(
        buyer=user,
        items__product=product,
        payment_status=Order.PaymentStatus.PAID,
    ).exclude(
        status__in=[Order.Status.CANCELLED, Order.Status.REFUNDED]
    ).exists()


def filtered_products(request):
    ensure_demo_catalog_data()
    products = Product.objects.select_related("seller", "community", "category").filter(
        status=Product.Status.ACTIVE
    )
    q = request.GET.get("q", "").strip()
    province = request.GET.get("province", "").strip()
    category_id = request.GET.get("category")
    community_id = request.GET.get("community")

    if q:
        products = products.filter(
            Q(name__icontains=q)
            | Q(description__icontains=q)
            | Q(seller__display_name__icontains=q)
            | Q(community__name__icontains=q)
        )
    if province:
        products = products.filter(community__province__icontains=province)
    if category_id:
        products = products.filter(category_id=category_id)
    if community_id:
        products = products.filter(community_id=community_id)
    return products


def product_list(request):
    communities = Community.objects.filter(is_active=True)
    category_products = Product.objects.filter(
        status=Product.Status.ACTIVE,
        image__isnull=False,
    ).exclude(image="").only("id", "category_id", "name", "image").order_by("-created_at")
    categories = Category.objects.filter(is_active=True).prefetch_related(
        Prefetch("products", queryset=category_products, to_attr="display_products")
    )
    context = {
        "products": filtered_products(request),
        "categories": categories,
        "communities": communities,
        "hero_slides": HomeSlide.objects.filter(is_active=True),
    }
    return render(request, "catalog/product_list.html", context)

def about(request):
    return render(request, "catalog/about.html")


def guide(request):
    return render(request, "catalog/guide.html")


def contact(request):
    return render(request, "catalog/contact.html", {"contact_email": settings.CONTACT_EMAIL})


def terms(request):
    return render(request, "catalog/terms.html")


def privacy(request):
    return render(request, "catalog/privacy.html")


def refund_policy(request):
    return render(request, "catalog/refund_policy.html")

def product_grid(request):
    return render(request, "catalog/_product_grid.html", {"products": filtered_products(request)})


def can_manage_product(user, product):
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_owner or product.seller_id == user.id:
        return True
    community = user_community(user) if user.is_cooperative_staff else None
    return bool(community and community.pk == product.community_id)

def product_detail(request, pk):
    product = get_object_or_404(
        Product.objects.select_related("seller", "community", "category").prefetch_related("images", "detail_images"),
        pk=pk,
    )
    if product.status != Product.Status.ACTIVE:
        community = user_community(request.user) if request.user.is_authenticated else None
        allowed = request.user.is_authenticated and (
            request.user.is_owner
            or product.seller_id == request.user.id
            or (request.user.is_cooperative_staff and community == product.community)
        )
        if not allowed:
            messages.error(request, "สินค้านี้ยังไม่เปิดขาย")
            return redirect("catalog:product_list")
    if product.status == Product.Status.ACTIVE:
        track_product_click(request, product)
    is_product_favorite = False
    is_seller_favorite = False
    if request.user.is_authenticated:
        is_product_favorite = ProductFavorite.objects.filter(user=request.user, product=product).exists()
        is_seller_favorite = SellerFavorite.objects.filter(user=request.user, seller=product.seller).exists()
    reviews = product.reviews.select_related("user").prefetch_related("media")
    sold_quantity = (
        product.order_items.filter(order__payment_status=Order.PaymentStatus.PAID)
        .aggregate(total=Sum("quantity"))["total"]
        or 0
    )
    seller_products = Product.objects.filter(
        seller=product.seller,
        status=Product.Status.ACTIVE,
    )
    seller_profile = getattr(product.seller, "farmer_profile", None)
    seller_rating = seller_products.aggregate(average=Avg("reviews__rating"))["average"] or 0
    related_filter = Q(community=product.community)
    if product.category_id:
        related_filter |= Q(category_id=product.category_id)
    recommended_products = list(
        Product.objects.select_related("seller", "community", "category")
        .prefetch_related("images")
        .filter(status=Product.Status.ACTIVE)
        .filter(related_filter)
        .exclude(pk=product.pk)
        .distinct()[:6]
    )
    if len(recommended_products) < 6:
        selected_ids = [item.pk for item in recommended_products]
        recommended_products.extend(
            Product.objects.select_related("seller", "community", "category")
            .prefetch_related("images")
            .filter(status=Product.Status.ACTIVE)
            .exclude(pk__in=[product.pk, *selected_ids])[: 6 - len(recommended_products)]
        )
    return render(
        request,
        "catalog/product_detail.html",
        {
            "product": product,
            "reviews": reviews,
            "review_count": reviews.count(),
            "sold_quantity": sold_quantity,
            "seller_profile": seller_profile,
            "seller_product_count": seller_products.count(),
            "seller_follower_count": product.seller.seller_favorited_by.count(),
            "seller_rating": seller_rating,
            "recommended_products": recommended_products,
            "is_product_favorite": is_product_favorite,
            "is_seller_favorite": is_seller_favorite,
            "can_review_product": can_review_product(request.user, product),
            "image_form": ProductImageForm(),
            "can_manage_product": can_manage_product(request.user, product),
            "can_moderate_product": can_manage_product(request.user, product)
            and (request.user.is_owner or request.user.is_cooperative_staff),
        },
    )


@login_required
def submit_review(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if not request.user.is_authenticated:
        messages.error(request, "กรุณาเข้าสู่ระบบก่อนเขียนรีวิว")
        return redirect(product)

    if not can_review_product(request.user, product):
        messages.error(request, "รีวิวได้เฉพาะผู้ที่ซื้อสินค้านี้และชำระเงินเรียบร้อยแล้ว")
        return redirect(product)

    if request.method == "POST":
        try:
            rating = int(request.POST.get("rating", 5))
        except (TypeError, ValueError):
            rating = 5
        rating = min(5, max(1, rating))
        comment = request.POST.get("comment", "").strip()
        media_files = request.FILES.getlist("media")
        if len(media_files) > 5:
            messages.error(request, "แนบรูปหรือวิดีโอได้สูงสุด 5 ไฟล์ต่อรีวิว")
            return redirect(product)

        try:
            review_media = [
                ProductReviewMedia(
                    file=uploaded_file,
                    media_type=review_media_type_for_upload(uploaded_file),
                )
                for uploaded_file in media_files
            ]
            for media in review_media:
                media.full_clean(exclude={"review"})
        except ValidationError as error:
            messages.error(request, error.messages[0])
            return redirect(product)

        review, _ = ProductReview.objects.update_or_create(
            product=product,
            user=request.user,
            defaults={"rating": rating, "comment": comment},
        )
        if media_files:
            review.media.all().delete()
            for media in review_media:
                media.review = review
                media.save()
        messages.success(request, "ส่งรีวิวแล้ว")
        return redirect(product)

    return redirect(product)


@login_required
def product_create(request):
    if not request.user.is_farmer:
        messages.error(request, "เฉพาะบัญชีเกษตรกรเท่านั้นที่ลงขายสินค้าได้")
        return redirect("accounts:dashboard")

    profile = getattr(request.user, "farmer_profile", None)
    if not profile or not profile.community or not profile.is_verified:
        messages.warning(request, "บัญชีเกษตรกรต้องได้รับการยืนยันจากเจ้าหน้าที่ก่อน")
        return redirect("accounts:dashboard")

    form = ProductForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        product = form.save(commit=False)
        gallery_images = use_first_gallery_image_as_cover(product, form.cleaned_data["image"])
        detail_images = form.cleaned_data["detail_images"]
        product.seller = request.user
        product.community = profile.community
        product.status = Product.Status.PENDING
        product.save()
        save_product_gallery_images(product, gallery_images)
        save_product_detail_images(product, detail_images)
        messages.success(request, "ส่งสินค้าให้เจ้าหน้าที่ตรวจสอบแล้ว")
        return redirect(product)

    return render(request, "catalog/product_form.html", {"form": form, "title": "เพิ่มสินค้า"})


@login_required
def product_update(request, pk):
    product = get_object_or_404(
        Product.objects.select_related("community", "seller").prefetch_related("images", "detail_images"),
        pk=pk,
    )
    if not can_manage_product(request.user, product):
        messages.error(request, "แก้ไขได้เฉพาะสินค้าในชุมชนที่คุณรับผิดชอบ")
        return redirect("accounts:staff_dashboard" if request.user.is_cooperative_staff else "accounts:dashboard")

    product_before = {
        "name": product.name,
        "price": str(product.price),
        "stock_quantity": str(product.stock_quantity),
        "status": product.status,
    }
    old_stock = product.stock_quantity
    old_image_name = product.image.name if product.image else ""
    old_harvest_date = product.harvest_date
    old_expiry_date = product.expiry_date
    form = ProductForm(request.POST or None, request.FILES or None, instance=product)
    if request.method == "POST" and form.is_valid():
        remove_image = request.POST.get("remove_image") == "1" and not request.FILES.get("image")
        gallery_images = form.cleaned_data["image"]
        detail_images = form.cleaned_data["detail_images"]
        with transaction.atomic():
            product = form.save(commit=False)
            # A browser date input can submit an empty value when it cannot render
            # a localized date. Keep existing dates unless an actual replacement was sent.
            if not request.POST.get("harvest_date") and old_harvest_date:
                product.harvest_date = old_harvest_date
            if not request.POST.get("expiry_date") and old_expiry_date:
                product.expiry_date = old_expiry_date
            if remove_image:
                product.image = ""
            elif not product.image and old_image_name:
                product.image = old_image_name
            gallery_images = use_first_gallery_image_as_cover(product, gallery_images)
            if request.user.is_farmer:
                product.status = Product.Status.PENDING
            product.save()
            save_product_gallery_images(product, gallery_images)
            save_product_detail_images(product, detail_images)
            if product.stock_quantity != old_stock:
                StockMovement.objects.create(
                    product=product,
                    movement_type=StockMovement.MovementType.MANUAL,
                    quantity_change=product.stock_quantity - old_stock,
                    balance_after=product.stock_quantity,
                    note=f"ปรับสต็อกโดย {request.user}",
                )
        if remove_image and old_image_name:
            Product._meta.get_field("image").storage.delete(old_image_name)
        record_audit(
            request,
            AuditEvent.Action.UPDATE,
            product,
            description="แก้ไขข้อมูลสินค้า",
            before=product_before,
            after={
                "name": product.name,
                "price": str(product.price),
                "stock_quantity": str(product.stock_quantity),
                "status": product.status,
            },
            community=product.community,
        )
        messages.success(request, "บันทึกสินค้าแล้ว")
        return redirect(product)

    return render(
        request,
        "catalog/product_form.html",
        {
            "form": form,
            "title": "แก้ไขสินค้า",
            "product": product,
            "is_staff_edit": request.user.is_cooperative_staff,
        },
    )

@login_required
def product_image_upload(request, pk):
    product = get_object_or_404(
        Product.objects.select_related("community", "seller"),
        pk=pk,
    )
    if not can_manage_product(request.user, product):
        messages.error(request, "เพิ่มรูปได้เฉพาะสินค้าในชุมชนที่คุณรับผิดชอบ")
        return redirect("accounts:staff_dashboard" if request.user.is_cooperative_staff else product)
    if request.method == "POST":
        form = ProductImageForm(request.POST, request.FILES)
        if form.is_valid():
            for image in form.cleaned_data["image"]:
                ProductImage.objects.create(
                    product=product,
                    image=image,
                    alt_text="",
                )
            if request.user.is_farmer:
                product.status = Product.Status.PENDING
                product.save(update_fields=["status", "updated_at"])
            messages.success(request, "เพิ่มรูปสินค้าแล้ว")
    return redirect(product)


@login_required
def product_image_delete(request, pk, image_id):
    product = get_object_or_404(
        Product.objects.select_related("community", "seller"),
        pk=pk,
    )
    image = get_object_or_404(ProductImage, pk=image_id, product=product)
    if not can_manage_product(request.user, product):
        messages.error(request, "ลบรูปได้เฉพาะสินค้าในชุมชนที่คุณรับผิดชอบ")
        return redirect("accounts:staff_dashboard" if request.user.is_cooperative_staff else product)
    if request.method == "POST":
        image.delete()
        if request.user.is_farmer:
            product.status = Product.Status.PENDING
            product.save(update_fields=["status", "updated_at"])
        messages.success(request, "ลบรูปสินค้าแล้ว")
    return redirect(product)

@role_required(User.Roles.COOPERATIVE_STAFF)
def product_review(request):
    products = Product.objects.select_related("seller", "community", "category").filter(
        status=Product.Status.PENDING
    )
    community = user_community(request.user)
    if not request.user.is_owner and community:
        products = products.filter(community=community)
    elif not request.user.is_owner:
        products = products.none()

    if request.method == "POST":
        product = get_object_or_404(products, pk=request.POST.get("product_id"))
        if not request.user.is_owner and not community:
            messages.error(request, "บัญชีเจ้าหน้าที่ยังไม่ได้ผูกกับชุมชน")
            return redirect("catalog:product_review")
        if not request.user.is_owner and community and product.community_id != community.id:
            messages.error(request, "อนุมัติได้เฉพาะสินค้าในชุมชนของคุณ")
            return redirect("catalog:product_review")

        form = ProductReviewForm(request.POST)
        if form.is_valid():
            if form.cleaned_data["decision"] == "approve":
                product.approve(request.user)
                messages.success(request, f"อนุมัติ {product.name} แล้ว")
            else:
                product.reject(request.user, form.cleaned_data["rejection_reason"])
                messages.warning(request, f"ไม่อนุมัติ {product.name}")
            return redirect("catalog:product_review")
    else:
        form = ProductReviewForm()

    return render(
        request,
        "catalog/product_review.html",
        {"products": products, "form": form, "community": community},
    )



@login_required
def toggle_product_favorite(request, pk):
    product = get_object_or_404(Product, pk=pk, status=Product.Status.ACTIVE)
    favorite = ProductFavorite.objects.filter(user=request.user, product=product).first()
    if request.method == "POST":
        if favorite:
            favorite.delete()
            messages.info(request, "นำสินค้าออกจากรายการถูกใจแล้ว")
        else:
            ProductFavorite.objects.create(user=request.user, product=product)
            messages.success(request, "เพิ่มสินค้าในรายการถูกใจแล้ว")
    return redirect(product)


@login_required
def toggle_seller_favorite(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if product.seller_id == request.user.id:
        messages.warning(request, "ไม่สามารถกดถูกใจร้านค้าของตัวเองได้")
        return redirect(product)
    favorite = SellerFavorite.objects.filter(user=request.user, seller=product.seller).first()
    if request.method == "POST":
        if favorite:
            favorite.delete()
            messages.info(request, "นำร้านค้าออกจากรายการถูกใจแล้ว")
        else:
            SellerFavorite.objects.create(user=request.user, seller=product.seller)
            messages.success(request, "เพิ่มร้านค้าในรายการถูกใจแล้ว")
    return redirect(product)


@login_required
def report_product(request, pk):
    product = get_object_or_404(Product.objects.select_related("seller", "community"), pk=pk)
    form = ReportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        report = form.save(commit=False)
        report.reporter = request.user
        report.target_type = Report.TargetType.PRODUCT
        report.product = product
        report.reported_user = product.seller
        report.community = product.community
        report.save()
        messages.success(request, "ส่งรายงานสินค้าแล้ว")
        return redirect(product)
    return render(request, "catalog/report_product.html", {"form": form, "product": product})


@login_required
def report_seller(request, pk):
    product = get_object_or_404(Product.objects.select_related("seller", "community"), pk=pk)
    if product.seller_id == request.user.id:
        messages.warning(request, "ไม่สามารถรายงานตัวเองได้")
        return redirect(product)
    form = ReportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        report = form.save(commit=False)
        report.reporter = request.user
        report.target_type = Report.TargetType.SELLER
        report.product = product
        report.reported_user = product.seller
        report.community = product.community
        report.save()
        messages.success(request, "ส่งรายงานผู้ขายแล้ว")
        return redirect(product)
    return render(request, "catalog/report_seller.html", {"form": form, "product": product})


@role_required(User.Roles.COOPERATIVE_STAFF)
def product_moderation_action(request, pk, action):
    product = get_object_or_404(Product.objects.select_related("seller", "community"), pk=pk)
    community = user_community(request.user)
    if not request.user.is_owner and (not community or product.community_id != community.id):
        messages.error(request, "จัดการได้เฉพาะสินค้าในชุมชนของคุณ")
        return redirect("accounts:dashboard")
    is_community_staff = request.user.is_cooperative_staff and not request.user.is_owner
    if is_community_staff and (
        (action == "block" and product.status != Product.Status.ACTIVE)
        or (action == "unblock" and product.status != Product.Status.BLOCKED)
        or action not in {"block", "unblock"}
    ):
        messages.error(request, "สถานะสินค้านี้ไม่สามารถจัดการด้วยคำสั่งที่เลือกได้")
        return redirect(product)
    if request.method == "POST":
        before_status = product.status
        if action == "block":
            product.block(request.user, request.POST.get("reason", ""))
            Notification.objects.create(
                user=product.seller,
                title="สินค้าถูกบล็อก",
                message=f"{product.name} ถูกบล็อกโดยเจ้าหน้าที่",
                link=product.get_absolute_url(),
            )
            messages.warning(request, "บล็อกสินค้าแล้ว")
        elif action == "unblock":
            product.unblock(request.user)
            Notification.objects.create(
                user=product.seller,
                title="ปลดบล็อกสินค้าแล้ว",
                message=f"{product.name} กลับมาเปิดขายอีกครั้ง",
                link=product.get_absolute_url(),
            )
            messages.success(request, "ปลดบล็อกสินค้าแล้ว")
        if action in {"block", "unblock"}:
            record_audit(
                request,
                AuditEvent.Action.BLOCK if action == "block" else AuditEvent.Action.UNBLOCK,
                product,
                description="เปลี่ยนสถานะสินค้า",
                before={"status": before_status},
                after={"status": product.status, "reason": product.rejection_reason},
                community=product.community,
            )
    return redirect(product)


@never_cache
def seller_store(request, seller_id):
    seller = get_object_or_404(User, pk=seller_id, role=User.Roles.FARMER, is_active=True)
    track_store_visit(request, seller)
    active_products = (
        Product.objects.select_related("community", "category")
        .prefetch_related("images")
        .filter(seller=seller, status=Product.Status.ACTIVE)
    )
    seller_profile = getattr(seller, "farmer_profile", None)
    categories = (
        Category.objects.filter(
            products__seller=seller,
            products__status=Product.Status.ACTIVE,
        )
        .annotate(
            store_product_count=Count(
                "products",
                filter=Q(
                    products__seller=seller,
                    products__status=Product.Status.ACTIVE,
                ),
                distinct=True,
            )
        )
        .distinct()
        .order_by("name")
    )
    recommended_products = list(
        active_products.annotate(favorite_count=Count("favorites", distinct=True))
        .order_by("-favorite_count", "-created_at")[:6]
    )

    products = active_products
    category_id = request.GET.get("category", "").strip()
    if category_id.isdigit():
        products = products.filter(category_id=int(category_id))

    sort = request.GET.get("sort", "popular")
    if sort == "latest":
        products = products.order_by("-created_at")
    elif sort == "bestselling":
        products = products.annotate(
            sold_quantity=Sum(
                "order_items__quantity",
                filter=Q(order_items__order__payment_status=Order.PaymentStatus.PAID),
                default=0,
            )
        ).order_by("-sold_quantity", "-created_at")
    elif sort == "price_asc":
        products = products.order_by("price", "name")
    elif sort == "price_desc":
        products = products.order_by("-price", "name")
    else:
        sort = "popular"
        products = products.annotate(
            favorite_count=Count("favorites", distinct=True)
        ).order_by("-favorite_count", "-created_at")

    featured_product = active_products.first()
    store_cover_slides = []
    if seller_profile:
        if seller_profile.store_cover:
            store_cover_slides.append(
                {
                    "url": seller_profile.store_cover.url,
                    "alt_text": f"รูปปก {seller_profile.farm_name or seller.username}",
                }
            )
        store_cover_slides.extend(
            {
                "url": slide.image.url,
                "alt_text": f"รูปสไลด์ {seller_profile.farm_name or seller.username}",
            }
            for slide in seller_profile.store_cover_slides.filter(is_active=True)
        )
    is_following = False
    if request.user.is_authenticated:
        is_following = SellerFavorite.objects.filter(
            user=request.user,
            seller=seller,
        ).exists()

    return render(
        request,
        "catalog/seller_store.html",
        {
            "seller": seller,
            "seller_profile": seller_profile,
            "products": products,
            "categories": categories,
            "recommended_products": recommended_products,
            "featured_product": featured_product,
            "store_cover_slides": store_cover_slides,
            "product_count": active_products.count(),
            "filtered_product_count": products.count(),
            "follower_count": seller.seller_favorited_by.count(),
            "seller_rating": active_products.aggregate(average=Avg("reviews__rating"))["average"] or 0,
            "current_category": category_id,
            "current_sort": sort,
            "is_following": is_following,
        },
    )

from django.db.models import Q
from rest_framework import permissions, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from accounts.decorators import user_community
from accounts.models import Community
from catalog.models import Category, Product
from orders.models import Order

from .serializers import (
    CategorySerializer,
    CommunitySerializer,
    OrderSerializer,
    ProductSerializer,
    UserSerializer,
)


class CommunityViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Community.objects.filter(is_active=True)
    serializer_class = CommunitySerializer


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Category.objects.filter(is_active=True)
    serializer_class = CategorySerializer


class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        products = Product.objects.select_related("seller", "community", "category")
        user = self.request.user
        if not user.is_authenticated:
            return products.filter(status=Product.Status.ACTIVE)
        if user.is_owner:
            return products
        if user.is_farmer:
            return products.filter(Q(status=Product.Status.ACTIVE) | Q(seller=user)).distinct()
        if user.is_cooperative_staff:
            community = user_community(user)
            if community:
                return products.filter(Q(status=Product.Status.ACTIVE) | Q(community=community)).distinct()
        return products.filter(status=Product.Status.ACTIVE)

    def perform_create(self, serializer):
        user = self.request.user
        profile = getattr(user, "farmer_profile", None)
        if not user.is_farmer or not profile or not profile.community or not profile.is_verified:
            raise PermissionDenied("บัญชีเกษตรกรต้องได้รับการยืนยันก่อนลงสินค้า")
        serializer.save(
            seller=user,
            community=profile.community,
            status=Product.Status.PENDING,
        )

    def perform_destroy(self, instance):
        user = self.request.user
        if not user.is_owner and instance.seller_id != user.id:
            raise PermissionDenied("ลบได้เฉพาะสินค้าของคุณ")
        instance.delete()

    def perform_update(self, serializer):
        product = self.get_object()
        user = self.request.user
        community = user_community(user) if user.is_cooperative_staff else None
        staff_in_scope = bool(community and product.community_id == community.id)
        if not user.is_owner and product.seller_id != user.id and not staff_in_scope:
            raise PermissionDenied("แก้ไขได้เฉพาะสินค้าที่อยู่ในความรับผิดชอบของคุณ")
        status = (
            product.status
            if user.is_owner or staff_in_scope
            else Product.Status.PENDING
        )
        serializer.save(status=status)


class OrderViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        orders = Order.objects.select_related("buyer", "seller", "community").prefetch_related("items")
        user = self.request.user
        if user.is_owner:
            return orders
        if user.is_farmer:
            return orders.filter(seller=user)
        if user.is_cooperative_staff:
            community = user_community(user)
            return orders.filter(community=community) if community else orders.none()
        return orders.filter(buyer=user)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def me(request):
    return Response(UserSerializer(request.user).data)

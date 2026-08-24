from rest_framework import serializers

from accounts.models import Community, User
from catalog.models import Category, Product, ProductImage
from orders.models import Order, OrderItem


class UserSerializer(serializers.ModelSerializer):
    role_label = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "display_name", "email", "phone", "role", "role_label"]
        read_only_fields = ["id", "role_label"]


class CommunitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Community
        fields = ["id", "name", "slug", "province", "district", "description"]


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug", "description"]


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["id", "image", "alt_text", "sort_order"]


class ProductSerializer(serializers.ModelSerializer):
    images = ProductImageSerializer(many=True, read_only=True)
    seller_name = serializers.SerializerMethodField()
    community_name = serializers.CharField(source="community.name", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    unit_label = serializers.CharField(source="get_unit_display", read_only=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "sku",
            "seller",
            "seller_name",
            "community",
            "community_name",
            "category",
            "category_name",
            "name",
            "description",
            "unit",
            "unit_label",
            "price",
            "stock_quantity",
            "minimum_order_quantity",
            "weight_grams",
            "image",
            "images",
            "harvest_date",
            "expiry_date",
            "status",
            "status_label",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "sku",
            "seller",
            "seller_name",
            "community",
            "community_name",
            "category_name",
            "images",
            "status",
            "status_label",
            "created_at",
            "updated_at",
        ]

    def get_seller_name(self, obj):
        return str(obj.seller)


class OrderItemSerializer(serializers.ModelSerializer):
    line_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = OrderItem
        fields = ["id", "product", "product_name", "unit", "quantity", "unit_price", "line_total"]


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    buyer_name = serializers.SerializerMethodField()
    seller_name = serializers.SerializerMethodField()
    community_name = serializers.CharField(source="community.name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    payment_status_label = serializers.CharField(source="get_payment_status_display", read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "reference",
            "buyer",
            "buyer_name",
            "seller",
            "seller_name",
            "community",
            "community_name",
            "status",
            "status_label",
            "payment_status",
            "payment_status_label",
            "subtotal",
            "shipping_fee",
            "discount_amount",
            "total_amount",
            "shipping_name",
            "shipping_phone",
            "shipping_address",
            "shipping_carrier",
            "tracking_number",
            "note",
            "items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_buyer_name(self, obj):
        return str(obj.buyer)

    def get_seller_name(self, obj):
        return str(obj.seller)
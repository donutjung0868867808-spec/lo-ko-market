from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("", views.order_list, name="order_list"),
    path("cart/", views.cart_detail, name="cart"),
    path("cart/checkout/", views.cart_checkout, name="cart_checkout"),
    path("cart/add/<int:product_id>/", views.cart_add, name="cart_add"),
    path("cart/update/<int:product_id>/", views.cart_update, name="cart_update"),
    path("cart/remove/<int:product_id>/", views.cart_remove, name="cart_remove"),
    path("checkout/<int:product_id>/", views.checkout, name="checkout"),
    path("<int:pk>/receipt/", views.order_receipt, name="order_receipt"),
    path("<int:pk>/", views.order_detail, name="order_detail"),
    path("<int:pk>/status/", views.order_update_status, name="order_update_status"),
    path("<int:pk>/cancel/", views.cancel_order, name="cancel_order"),
    path("<int:pk>/confirm-received/", views.confirm_received, name="confirm_received"),
    path("<int:pk>/report-buyer/", views.report_buyer, name="report_buyer"),
]

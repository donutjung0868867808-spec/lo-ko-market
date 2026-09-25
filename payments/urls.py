from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("checkout/<int:order_id>/", views.create_checkout_session, name="create_checkout"),
    path("checkout/<int:order_id>/demo/", views.demo_checkout, name="demo_checkout"),
    path("checkout/<int:order_id>/demo/complete/", views.complete_demo_checkout, name="complete_demo_checkout"),
    path("success/", views.success, name="success"),
    path("cancel/<int:order_id>/", views.cancel, name="cancel"),
    path("refund/<int:order_id>/request/", views.request_refund, name="request_refund"),
    path("refund/<int:refund_id>/reject/", views.reject_refund, name="reject_refund"),
    path("refund/<int:refund_id>/process/", views.process_refund, name="process_refund"),
    path("methods/setup/", views.create_payment_method_setup, name="create_payment_method_setup"),
    path("methods/setup/success/", views.payment_method_setup_success, name="payment_method_setup_success"),
    path("methods/<int:pk>/default/", views.payment_method_set_default, name="payment_method_set_default"),
    path("methods/<int:pk>/delete/", views.payment_method_delete, name="payment_method_delete"),
    path("connect/start/", views.connect_account, name="connect_account"),
    path("connect/return/", views.connect_return, name="connect_return"),
    path("stripe/webhook/", views.stripe_webhook, name="stripe_webhook"),
    path("stripe/connect/webhook/", views.stripe_webhook, {"connect": True}, name="stripe_connect_webhook"),
]

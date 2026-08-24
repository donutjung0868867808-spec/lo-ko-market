from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("", views.product_list, name="product_list"),
    path("about/", views.about, name="about"),
    path("guide/", views.guide, name="guide"),
    path("contact/", views.contact, name="contact"),
    path("terms/", views.terms, name="terms"),
    path("privacy/", views.privacy, name="privacy"),
    path("refund-policy/", views.refund_policy, name="refund_policy"),
    path("products/grid/", views.product_grid, name="product_grid"),
    path("products/new/", views.product_create, name="product_create"),
    path("products/review/", views.product_review, name="product_review"),
    path("sellers/<int:seller_id>/", views.seller_store, name="seller_store"),
    path("products/<int:pk>/", views.product_detail, name="product_detail"),
    path("products/<int:pk>/review/", views.submit_review, name="submit_review"),
    path("products/<int:pk>/edit/", views.product_update, name="product_update"),
    path("products/<int:pk>/images/", views.product_image_upload, name="product_image_upload"),
    path("products/<int:pk>/images/<int:image_id>/delete/", views.product_image_delete, name="product_image_delete"),
    path("products/<int:pk>/favorite/", views.toggle_product_favorite, name="toggle_product_favorite"),
    path("products/<int:pk>/seller-favorite/", views.toggle_seller_favorite, name="toggle_seller_favorite"),
    path("products/<int:pk>/report-product/", views.report_product, name="report_product"),
    path("products/<int:pk>/report-seller/", views.report_seller, name="report_seller"),
    path("products/<int:pk>/moderate/<str:action>/", views.product_moderation_action, name="product_moderation_action"),
]

from django.conf import settings


def payment_mode(request):
    return {"payment_is_test_mode": settings.PAYMENT_MODE == "test"}

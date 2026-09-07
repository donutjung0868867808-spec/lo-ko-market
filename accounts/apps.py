from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "accounts"
    verbose_name = "บัญชีผู้ใช้และการดูแลชุมชน"

    def ready(self):
        from . import realtime_signals

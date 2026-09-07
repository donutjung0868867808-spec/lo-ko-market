"""
ASGI config for agri_market project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_market.settings')

django_application = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.urls import path, re_path
from accounts.consumers import AuthenticatedConsumer, ChatConsumer

application = ProtocolTypeRouter({
    "http": django_application,
    "websocket": AllowedHostsOriginValidator(URLRouter([
        path("ws/events/", AuthenticatedConsumer.as_asgi()),
        path("ws/admin/events/", AuthenticatedConsumer.as_asgi()),
        re_path(r"^ws/(?:admin/)?chat/(?P<kind>direct|support)/(?P<pk>[0-9]+)/$", ChatConsumer.as_asgi()),
    ])),
})

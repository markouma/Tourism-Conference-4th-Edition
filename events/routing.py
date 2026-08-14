# app/routing.py
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/exhibitor/(?P<booth_id>\d+)/$', consumers.ExhibitorConsumer.as_asgi()),
    re_path(r'ws/user/(?P<user_id>\d+)/$', consumers.UserVisitsConsumer.as_asgi()),
]

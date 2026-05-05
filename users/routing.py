from django.urls import re_path
from .consumers.chat_consumer import ChatConsumer
from .consumers.chat_updates_consumer import ChatUpdatesConsumer

websocket_urlpatterns = [
    re_path(r'ws/chat/(?P<other_user_id>\d+)/$', ChatConsumer.as_asgi()),
    re_path(r'ws/chat-updates/$', ChatUpdatesConsumer.as_asgi()),
]
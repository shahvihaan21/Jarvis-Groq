from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.new_chat, name="new_chat"),
    path("test-frontend/", views.test_frontend, name="test_frontend"),
    path("api/chat/", views.chat_api, name="chat_api"),
    path("api/tools/", views.tools_api, name="tools_api"),
    path("api/health/", views.health, name="health"),
]

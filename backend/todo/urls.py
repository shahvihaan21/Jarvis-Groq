from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("c/<uuid:conversation_id>/", views.index, name="conversation_detail"),
    path("new/", views.new_chat, name="new_chat"),
    path("delete/<uuid:conversation_id>/", views.delete_chat, name="delete_chat"),
    path("api/chat/", views.chat_api, name="chat_api"),
]


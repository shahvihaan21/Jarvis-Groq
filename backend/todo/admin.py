from django.contrib import admin
from .models import Conversation, ChatMessage

class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    readonly_fields = ('created_at',)

@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('title', 'created_at', 'updated_at', 'id')
    search_fields = ('title', 'id')
    inlines = [ChatMessageInline]

@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('sender', 'conversation', 'created_at', 'short_content')
    list_filter = ('sender', 'created_at')
    search_fields = ('content',)

    def short_content(self, obj):
        return obj.content[:50]
    short_content.short_description = 'Content'



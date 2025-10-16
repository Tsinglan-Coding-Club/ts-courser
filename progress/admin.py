from django.contrib import admin
from .models import UserProgress, EpisodeReadStatus


@admin.register(UserProgress)
class UserProgressAdmin(admin.ModelAdmin):
    list_display = ['user', 'course', 'current_episode', 'updated_at']
    list_filter = ['course', 'updated_at']
    search_fields = ['user__username', 'user__email', 'course__title']
    raw_id_fields = ['user', 'course', 'current_episode']


@admin.register(EpisodeReadStatus)
class EpisodeReadStatusAdmin(admin.ModelAdmin):
    list_display = ['user', 'episode', 'is_read', 'marked_at']
    list_filter = ['is_read', 'marked_at']
    search_fields = ['user__username', 'episode__title']
    raw_id_fields = ['user', 'episode']

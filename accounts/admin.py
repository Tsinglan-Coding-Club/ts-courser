from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Custom User admin with role and verification fields.
    """
    list_display = ['username', 'email', 'role', 'is_verified_teacher', 'is_staff', 'created_at']
    list_filter = ['role', 'is_verified_teacher', 'is_staff', 'is_active']
    search_fields = ['username', 'email', 'first_name', 'last_name']

    fieldsets = BaseUserAdmin.fieldsets + (
        ('Additional Info', {
            'fields': ('role', 'is_verified_teacher', 'created_at')
        }),
    )
    readonly_fields = ['created_at']

    # Allow admins to quickly verify teachers
    actions = ['verify_teachers', 'unverify_teachers']

    def verify_teachers(self, request, queryset):
        updated = queryset.filter(role='teacher').update(is_verified_teacher=True)
        self.message_user(request, f'{updated} teacher(s) verified successfully.')
    verify_teachers.short_description = 'Verify selected teachers'

    def unverify_teachers(self, request, queryset):
        updated = queryset.filter(role='teacher').update(is_verified_teacher=False)
        self.message_user(request, f'{updated} teacher(s) unverified.')
    unverify_teachers.short_description = 'Unverify selected teachers'

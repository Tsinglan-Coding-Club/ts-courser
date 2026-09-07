from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from .forms import AdminLocalUserCreationForm
from .models import ExternalIdentity, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Custom User admin with role and verification fields.
    """
    add_form = AdminLocalUserCreationForm
    list_display = [
        'username', 'email', 'role', 'local_login_enabled',
        'must_change_credentials', 'is_verified_teacher', 'is_staff', 'created_at',
    ]
    list_filter = [
        'role', 'local_login_enabled', 'must_change_credentials',
        'is_verified_teacher', 'is_staff', 'is_active',
    ]
    search_fields = ['username', 'email', 'first_name', 'last_name']

    fieldsets = BaseUserAdmin.fieldsets + (
        ('Additional Info', {
            'fields': (
                'role', 'is_verified_teacher', 'teacher_reviewed_at',
                'teacher_reviewed_by', 'local_login_enabled',
                'must_change_credentials', 'initial_password_expires_at',
                'password_changed_at', 'created_by', 'created_at',
            )
        }),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'role', 'password1', 'password2'),
        }),
    )
    readonly_fields = [
        'created_at', 'password_changed_at', 'created_by',
        'teacher_reviewed_at', 'teacher_reviewed_by',
    ]

    # Allow admins to quickly verify teachers
    actions = ['verify_teachers', 'unverify_teachers']

    def verify_teachers(self, request, queryset):
        updated = queryset.filter(role='teacher').update(
            is_verified_teacher=True,
            teacher_reviewed_at=timezone.now(),
            teacher_reviewed_by=request.user,
        )
        self.message_user(request, f'{updated} teacher(s) verified successfully.')
    verify_teachers.short_description = 'Verify selected teachers'

    def unverify_teachers(self, request, queryset):
        updated = queryset.filter(role='teacher').update(
            is_verified_teacher=False,
            teacher_reviewed_at=timezone.now(),
            teacher_reviewed_by=request.user,
        )
        self.message_user(request, f'{updated} teacher(s) unverified.')
    unverify_teachers.short_description = 'Unverify selected teachers'

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            if not change and obj.role != 'student':
                raise PermissionDenied('Only a superuser can create a local administrator.')
            if change:
                original = User.objects.get(pk=obj.pk)
                protected_fields = (
                    'role', 'is_staff', 'is_superuser', 'local_login_enabled',
                )
                if any(
                    getattr(original, field) != getattr(obj, field)
                    for field in protected_fields
                ):
                    raise PermissionDenied('Only a superuser can change authentication privileges.')
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if not request.user.is_superuser and obj is None and 'role' in form.base_fields:
            form.base_fields['role'].choices = [('student', 'Student')]
        return form

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            fields.extend((
                'role', 'is_staff', 'is_superuser', 'groups',
                'user_permissions', 'local_login_enabled',
                'must_change_credentials', 'initial_password_expires_at',
            ))
        return fields

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_admin

    def has_view_permission(self, request, obj=None):
        if (
            obj is not None
            and not request.user.is_superuser
            and (obj.is_superuser or obj.role == 'admin')
        ):
            return False
        return request.user.is_admin

    def has_add_permission(self, request):
        return request.user.is_admin

    def has_change_permission(self, request, obj=None):
        if (
            obj is not None
            and not request.user.is_superuser
            and (obj.is_superuser or obj.role == 'admin')
        ):
            return False
        return request.user.is_admin

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(ExternalIdentity)
class ExternalIdentityAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'provider', 'tenant_id', 'object_id', 'principal_name',
        'last_authenticated_at',
    ]
    search_fields = ['user__username', 'principal_name', 'tenant_id', 'object_id']
    readonly_fields = [
        'user', 'provider', 'tenant_id', 'object_id', 'principal_name',
        'display_name', 'created_at', 'last_authenticated_at',
    ]

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_admin

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_admin

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

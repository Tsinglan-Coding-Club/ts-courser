import os

from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models


class UserManager(DjangoUserManager):
    """Keep controlled superuser bootstrap aligned with platform roles."""

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('role', 'admin')
        extra_fields.setdefault('local_login_enabled', True)
        extra_fields.setdefault('must_change_credentials', False)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    """
    Custom User model extending Django's AbstractUser.
    Supports three roles: student, teacher, and admin.
    """
    ROLE_CHOICES = [
        ('student', 'Student'),
        ('teacher', 'Teacher'),
        ('admin', 'Admin'),
    ]
    REQUIRED_FIELDS = []

    email = models.EmailField(
        blank=True,
        default='',
        help_text='Optional contact email; never used as an identity key',
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='student')
    is_verified_teacher = models.BooleanField(
        default=False,
        help_text='Whether this teacher has been verified by an admin'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # Authentication state. Microsoft-only users have an unusable password and
    # local_login_enabled=False. Accounts issued by an administrator must replace
    # both their temporary username and password before entering the platform.
    local_login_enabled = models.BooleanField(default=False)
    must_change_credentials = models.BooleanField(default=False)
    initial_password_expires_at = models.DateTimeField(null=True, blank=True)
    password_changed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='created_accounts',
    )
    teacher_reviewed_at = models.DateTimeField(null=True, blank=True)
    teacher_reviewed_by = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='reviewed_teachers',
    )

    # Profile fields
    display_name = models.CharField(max_length=100, blank=True, help_text='Display name shown to other users')
    bio = models.TextField(max_length=500, blank=True, help_text='Personal bio or introduction')
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True, help_text='User profile avatar')
    favorite_tags = models.ManyToManyField('courses.Tag', blank=True, related_name='favorited_by', help_text='User preferred tags')

    objects = UserManager()

    def __str__(self):
        return f"{self.username} ({self.role})"

    @property
    def is_student(self):
        return self.role == 'student'

    @property
    def is_teacher(self):
        return self.role == 'teacher' and self.is_verified_teacher

    @property
    def is_admin(self):
        return self.role == 'admin' or self.is_superuser

    @property
    def get_display_name(self):
        """Return display name or username as fallback"""
        return self.display_name if self.display_name else self.username

    def get_avatar_url(self):
        """Return avatar URL or default avatar"""
        if self.avatar:
            return self.avatar.url
        return '/static/images/default-avatar.png'

    def delete_old_avatar(self):
        """Delete old avatar file when uploading new one"""
        if self.avatar:
            if os.path.isfile(self.avatar.path):
                os.remove(self.avatar.path)


class ExternalIdentity(models.Model):
    """A durable Microsoft identity binding keyed by tenant and object ID."""

    PROVIDER_MICROSOFT = 'microsoft'

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='external_identity',
    )
    provider = models.CharField(max_length=32, default=PROVIDER_MICROSOFT)
    tenant_id = models.CharField(max_length=36)
    object_id = models.CharField(max_length=36)
    principal_name = models.CharField(max_length=254, blank=True)
    display_name = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_authenticated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('provider', 'tenant_id', 'object_id'),
                name='unique_external_identity',
            ),
        ]

    def __str__(self):
        return f'{self.provider}:{self.tenant_id}:{self.object_id}'

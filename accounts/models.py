from django.db import models
from django.contrib.auth.models import AbstractUser
import os


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

    email = models.EmailField(unique=True, help_text='Email address for login')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='student')
    is_verified_teacher = models.BooleanField(
        default=False,
        help_text='Whether this teacher has been verified by an admin'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # Profile fields
    display_name = models.CharField(max_length=100, blank=True, help_text='Display name shown to other users')
    bio = models.TextField(max_length=500, blank=True, help_text='Personal bio or introduction')
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True, help_text='User profile avatar')
    favorite_tags = models.ManyToManyField('courses.Tag', blank=True, related_name='favorited_by', help_text='User preferred tags')

    # Email verification fields
    email_verification_code = models.CharField(max_length=6, blank=True, help_text='6-digit verification code')
    email_verification_sent_at = models.DateTimeField(null=True, blank=True, help_text='When verification code was sent')
    is_email_verified = models.BooleanField(default=False, help_text='Whether email has been verified')

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
        return self.role == 'admin' or self.is_staff

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

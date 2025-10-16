from django.db import models
from django.contrib.auth.models import AbstractUser


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

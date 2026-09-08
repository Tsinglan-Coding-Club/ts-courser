from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import User


@transaction.atomic
def issue_local_student(*, creator, username, initial_password, display_name, email=''):
    """Create a student with credentials chosen by the administrator."""
    expires_at = timezone.now() + timedelta(
        days=settings.LOCAL_INITIAL_PASSWORD_TTL_DAYS,
    )
    user = User.objects.create_user(
        username=username,
        password=initial_password,
        email=email,
        display_name=display_name,
        role='student',
        local_login_enabled=True,
        must_change_credentials=True,
        initial_password_expires_at=expires_at,
        created_by=creator,
    )
    return user

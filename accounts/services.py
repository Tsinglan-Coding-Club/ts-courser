import secrets
import string
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import User


INITIAL_PASSWORD_ALPHABET = (
    'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
)


def _generated_username():
    for _ in range(20):
        username = f'student-{secrets.token_hex(4)}'
        if not User.objects.filter(username__iexact=username).exists():
            return username
    raise RuntimeError('Unable to generate a unique username.')


def _generated_password(length=14):
    return ''.join(secrets.choice(INITIAL_PASSWORD_ALPHABET) for _ in range(length))


@transaction.atomic
def issue_local_student(*, creator, username='', display_name, email=''):
    """Create one student credential and return its one-time plaintext password."""
    username = username or _generated_username()
    password = _generated_password()
    expires_at = timezone.now() + timedelta(
        days=settings.LOCAL_INITIAL_PASSWORD_TTL_DAYS,
    )
    user = User.objects.create_user(
        username=username,
        password=password,
        email=email,
        display_name=display_name,
        role='student',
        local_login_enabled=True,
        must_change_credentials=True,
        initial_password_expires_at=expires_at,
        created_by=creator,
    )
    return user, password

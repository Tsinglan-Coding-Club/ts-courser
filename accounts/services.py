import re
import unicodedata
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import User


def student_username_from_name(display_name):
    normalized = unicodedata.normalize('NFKD', display_name.casefold())
    # Leave room for suffixes even when Unicode normalization expands a name.
    username = re.sub(r'[^a-z0-9]', '', normalized)[:100]
    if not username:
        raise ValidationError('Enter an English name or pinyin containing letters or numbers.')
    return username


def plan_local_students(display_names):
    """Allocate readable, case-insensitively unique usernames for a preview."""
    bases = [student_username_from_name(name) for name in display_names]
    if not bases:
        return []
    query = Q()
    for base in set(bases):
        query |= Q(username__istartswith=base)
    used = {
        username.casefold()
        for username in User.objects.filter(query).values_list('username', flat=True)
    }
    students = []
    for name, base in zip(display_names, bases):
        username = base
        number = 2
        while username in used:
            suffix = str(number)
            username = base[:150 - len(suffix)] + suffix
            number += 1
        used.add(username)
        students.append({'display_name': name, 'username': username})
    return students


@transaction.atomic
def issue_local_students(*, creator, students, initial_password):
    """Create the reviewed batch atomically, without changing its usernames."""
    query = Q()
    for student in students:
        query |= Q(username__iexact=student['username'])
    if not students or User.objects.filter(query).exists():
        raise ValidationError('A username is now in use. Preview the names again before creating accounts.')
    return [
        issue_local_student(
            creator=creator, initial_password=initial_password, **student,
        )
        for student in students
    ]


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

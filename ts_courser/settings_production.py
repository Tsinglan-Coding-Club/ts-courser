"""Production settings for deployments behind HTTPS."""

import os
from urllib.parse import urlsplit
from uuid import UUID

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F403


def _required(name):
    value = os.environ.get(name, '').strip()
    if not value:
        raise ImproperlyConfigured(f'{name} must be set in production')
    return value


def _csv(name):
    values = [item.strip() for item in _required(name).split(',') if item.strip()]
    if not values or any(value == '*' or '*' in value for value in values):
        raise ImproperlyConfigured(
            f'{name} must contain one or more explicit hosts; wildcards are not allowed'
        )
    return values


SECRET_KEY = _required('DJANGO_SECRET_KEY')
if (
    len(SECRET_KEY) < 50
    or len(set(SECRET_KEY)) < 5
    or SECRET_KEY.startswith(('django-insecure-', 'dev-only-', 'replace-with-'))
):
    raise ImproperlyConfigured(
        'DJANGO_SECRET_KEY must be a long, unique production secret'
    )
ALLOWED_HOSTS = _csv('DJANGO_ALLOWED_HOSTS')
DEBUG = False

# Keep the production SQLite database in a writable, site-local runtime
# directory. The source tree remains read-only for the www service account.
DATABASES['default']['NAME'] = os.environ.get(
    'DJANGO_DB_PATH',
    BASE_DIR / 'db.sqlite3',
)

MS_ENTRA_TENANT_ID = _required('MS_ENTRA_TENANT_ID')
MS_ENTRA_CLIENT_ID = _required('MS_ENTRA_CLIENT_ID')
MS_ENTRA_CLIENT_SECRET = _required('MS_ENTRA_CLIENT_SECRET')
MS_ENTRA_REDIRECT_URI = _required('MS_ENTRA_REDIRECT_URI')
MS_ENTRA_AUTHORITY = f'https://login.microsoftonline.com/{MS_ENTRA_TENANT_ID}'
MS_ENTRA_ENABLED = True

try:
    UUID(MS_ENTRA_TENANT_ID)
    UUID(MS_ENTRA_CLIENT_ID)
except ValueError as exc:
    raise ImproperlyConfigured(
        'MS_ENTRA_TENANT_ID and MS_ENTRA_CLIENT_ID must be UUIDs'
    ) from exc

if MS_ENTRA_TENANT_ID.lower() != '7222912a-435d-423b-b22b-74b909c3bf8b':
    raise ImproperlyConfigured('MS_ENTRA_TENANT_ID does not match the school tenant')
if MS_ENTRA_CLIENT_ID.lower() != '5910709e-99db-4cc0-9468-88497aa32f23':
    raise ImproperlyConfigured('MS_ENTRA_CLIENT_ID does not match the registered app')

_entra_redirect = urlsplit(MS_ENTRA_REDIRECT_URI)
if (
    _entra_redirect.scheme != 'https'
    or _entra_redirect.netloc != 'courser.tsinglan.top'
    or _entra_redirect.path != '/accounts/microsoft/callback/'
    or _entra_redirect.query
    or _entra_redirect.fragment
):
    raise ImproperlyConfigured(
        'MS_ENTRA_REDIRECT_URI must be the registered production callback'
    )
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',')
    if origin.strip()
]

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_SECURE_HSTS_SECONDS', '31536000'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get(
    'DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS', 'true'
).lower() in {'1', 'true', 'yes', 'on'}
SECURE_HSTS_PRELOAD = os.environ.get(
    'DJANGO_SECURE_HSTS_PRELOAD', 'false'
).lower() in {'1', 'true', 'yes', 'on'}
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'

# Set this only when the TLS-terminating proxy is known to set X-Forwarded-Proto.
if os.environ.get('DJANGO_USE_PROXY_SSL_HEADER', '').lower() in {'1', 'true', 'yes', 'on'}:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

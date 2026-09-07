"""Production settings for deployments behind HTTPS."""

import os

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

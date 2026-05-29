"""
WSGI config for ts_courser project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ts_courser.settings')

application = get_wsgi_application()

# ===========================================================================
# Inject COOP/COEP headers into ALL responses — including static files.
#
# PROBLEM:
#   Django's runserver uses StaticFilesHandler as the outermost WSGI layer.
#   Static file responses bypass Django middleware entirely. Without COOP/COEP
#   on static files, Web Workers cannot use SharedArrayBuffer — Python input()
#   breaks and the entire Pyodide worker silently fails.
#
# SOLUTION:
#   Monkey-patch StaticFilesHandler.serve() to add headers directly onto the
#   HttpResponse object. Unlike patching __call__ (which has complex WSGI
#   interaction), modifying the returned HttpResponse is guaranteed to work.
#
# WARNING: This patch depends on Django's internal StaticFilesHandler.serve()
#   signature (tested with Django 5.2). If Django changes this method in a
#   future version, this patch may silently break. Verify after upgrades.
#
#   In production, use nginx/caddy to set these headers instead.
# ===========================================================================

_headers_to_add = [
    ('Cross-Origin-Opener-Policy', 'same-origin'),
    ('Cross-Origin-Embedder-Policy', 'credentialless'),
]


def _add_security_headers(response):
    """Add COOP/COEP headers to an HttpResponse in-place."""
    for key, value in _headers_to_add:
        if key not in response:
            response[key] = value


# ---- Patch StaticFilesHandler.serve (static file responses) ----

from django.contrib.staticfiles.handlers import StaticFilesHandler as _SFH

_original_sfh_serve = _SFH.serve


def _patched_sfh_serve(self, request):
    response = _original_sfh_serve(self, request)
    _add_security_headers(response)
    return response


_SFH.serve = _patched_sfh_serve


"""
Custom middleware for TS-Courser.

NOTE: COOP/COEP headers are also set by the monkey-patch in wsgi.py
(which covers static file responses that bypass Django middleware).
Both are needed — this middleware covers Django view responses (pages, APIs),
while wsgi.py covers static files (.js, .mjs, .wasm).
"""

from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse


class CrossOriginIsolationMiddleware:
    """
    Adds COOP and COEP headers required for SharedArrayBuffer.
    SharedArrayBuffer is needed by Pyodide Web Worker for synchronous
    stdin (Python input() support) via Atomics.wait() and the
    interrupt buffer for the Stop button.

    Uses COEP: credentialless (instead of require-corp) so that
    cross-origin CDN resources (Bootstrap, marked.js, PDF.js, Monaco)
    are NOT blocked. credentialless mode still enables cross-origin
    isolation and SharedArrayBuffer.

    Browser support: Chrome 96+, Firefox 122+, Edge 96+, Safari 17+.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response['Cross-Origin-Opener-Policy'] = 'same-origin'
        response['Cross-Origin-Embedder-Policy'] = 'credentialless'
        return response


class AccountStateMiddleware:
    """Confine pending or temporary accounts before business views run."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return self.get_response(request)

        path = request.path
        if path.startswith('/static/'):
            return self.get_response(request)

        if user.must_change_credentials:
            if path == reverse('accounts:logout'):
                return self.get_response(request)
            return self._blocked(request, 'credentials', 'accounts:login')

        if user.role == 'teacher' and not user.is_verified_teacher:
            allowed = {
                reverse('accounts:teacher_pending'),
                reverse('accounts:logout'),
            }
            if path not in allowed:
                return self._blocked(
                    request,
                    'teacher_pending',
                    'accounts:teacher_pending',
                )

        return self.get_response(request)

    @staticmethod
    def _blocked(request, state, redirect_name):
        if (
            request.path.startswith(('/api/', '/accounts/api/'))
            or 'application/json' in request.headers.get('Accept', '')
        ):
            return JsonResponse(
                {'success': False, 'error': 'Account setup is incomplete.', 'account_state': state},
                status=403,
            )
        return redirect(redirect_name)

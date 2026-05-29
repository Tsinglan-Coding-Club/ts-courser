"""
Custom middleware for TS-Courser.

NOTE: COOP/COEP headers are also set by the monkey-patch in wsgi.py
(which covers static file responses that bypass Django middleware).
Both are needed — this middleware covers Django view responses (pages, APIs),
while wsgi.py covers static files (.js, .mjs, .wasm).
"""


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

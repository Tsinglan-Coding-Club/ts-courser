"""
Custom context processors for ts_courser project.
"""

from django.conf import settings


def version_context(request):
    """
    Add VERSION to all template contexts.
    """
    return {
        'VERSION': settings.VERSION
    }

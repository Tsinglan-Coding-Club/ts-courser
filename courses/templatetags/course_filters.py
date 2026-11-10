import os

from django import template
from django.templatetags.static import static

from courses.icons import section_icon_catalog

register = template.Library()


@register.inclusion_tag('courses/_section_icon.html')
def section_icon(value):
    icon = (
        section_icon_catalog().get(value)
        if value and value.startswith(('devicon:', 'heroicons:')) else None
    )
    return {
        'icon_url': static(icon['path']) if icon else '',
        'is_heroicon': bool(icon and value.startswith('heroicons:')),
        'emoji': value if not icon else '',
    }


@register.filter
def basename(value):
    """Extract the filename from a full path."""
    if not value:
        return ''
    return os.path.basename(value)

# Episode type → display config mapping (badge CSS class, icon class, label)
EPISODE_TYPE_CONFIG = {
    'material': {'badge': 'bg-primary', 'icon': 'bi-file-text',       'label': 'Material'},
    'quiz':     {'badge': 'bg-success', 'icon': 'bi-question-circle', 'label': 'Quiz'},
    'code':     {'badge': 'bg-info',    'icon': 'bi-code',            'label': 'Code'},
    'paper':    {'badge': 'bg-warning', 'icon': 'bi-file-earmark-pdf','label': 'Paper'},
}


@register.filter
def get_item(dictionary, key):
    """Get item from dictionary by key."""
    if dictionary is None:
        return None
    return dictionary.get(key)


@register.filter
def episode_type_config(episode_type):
    """Return display config dict for an episode type string."""
    return EPISODE_TYPE_CONFIG.get(
        episode_type,
        {'badge': 'bg-secondary', 'icon': 'bi-file', 'label': episode_type},
    )

from django import template

register = template.Library()

# Episode type → display config mapping (badge CSS class, icon class, label)
EPISODE_TYPE_CONFIG = {
    'material': {'badge': 'bg-primary', 'icon': 'bi-file-text', 'label': 'Material'},
    'quiz':     {'badge': 'bg-success', 'icon': 'bi-question-circle', 'label': 'Quiz'},
    'code':     {'badge': 'bg-info',    'icon': 'bi-code-slash',          'label': 'Code'},
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

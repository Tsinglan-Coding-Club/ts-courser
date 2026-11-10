"""Local section icon catalog shared by authoring and template rendering."""

from functools import lru_cache
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.templatetags.static import static

from .common_devicons import COMMON_DEVICONS
from .heroicon_categories import heroicon_category


@lru_cache(maxsize=1)
def section_icon_catalog():
    packages = settings.BASE_DIR / 'node_modules'
    catalog = {}
    devicon = packages / 'devicon'
    for entry in json.loads((devicon / 'devicon.json').read_text(encoding='utf-8')):
        name = entry['name']
        for variant in entry['versions']['svg']:
            filename = f'{name}/{name}-{variant}.svg'
            if not (devicon / 'icons' / filename).is_file():
                continue
            key = f'devicon:{name}:{variant}'
            catalog[key] = {
                'name': key,
                'path': f'vendor/devicon/{filename}',
                'shortcodes': [name, f'{name}-{variant}', *entry.get('altnames', [])],
                'category': 'Devicon',
                'filter': 'devicon',
                'browse': name in COMMON_DEVICONS,
            }
    for style in ('outline', 'solid'):
        for path in sorted((packages / 'heroicons' / '24' / style).glob('*.svg')):
            key = f'heroicons:24-{style}:{path.stem}'
            catalog[key] = {
                'name': key,
                'path': f'vendor/heroicons/24/{style}/{path.name}',
                'shortcodes': [path.stem, f'{path.stem}-{style}'],
                'category': f'Heroicons · {style.title()}',
                'filter': heroicon_category(path.stem),
            }
    return catalog


def section_icon_choices():
    return [
        {
            'name': icon['name'],
            'url': static(icon['path']),
            'shortcodes': icon['shortcodes'],
            'category': icon['category'],
            'filter': icon['filter'],
            'browse': icon.get('browse', True),
        }
        for icon in section_icon_catalog().values()
    ]


def validate_section_icon(value):
    if value.startswith(('devicon:', 'heroicons:')):
        if value not in section_icon_catalog():
            raise ValidationError('Choose an icon from the picker.')
    elif len(value) > 32:
        raise ValidationError('Emoji must contain at most 32 characters.')

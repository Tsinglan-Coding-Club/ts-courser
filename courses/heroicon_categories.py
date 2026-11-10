"""Browse categories shared by the outline and solid variants of each Heroicon."""

# Each entry matches an icon name or a whole name segment prefix, so variants
# such as document-text and folder-open stay together.
HEROICON_FAMILIES = {
    'navigation': '''
        arrow arrows bars chevron cursor ellipsis home link magnifying-glass
        view-columns viewfinder window
    ''',
    'files': '''
        archive backspace bold book bookmark clipboard document folder h1 h2 h3
        italic list-bullet newspaper numbered-list paper-clip pencil printer queue
        rectangle scissors square squares strikethrough trash underline
    ''',
    'communication': '''
        at bell chat envelope face hand heart identification inbox language
        megaphone paper-airplane phone rss share user users
    ''',
    'media': '''
        backward camera eye-dropper film forward gif microphone musical-note
        paint-brush pause photo play radio speaker stop swatch tv video-camera
    ''',
    'tools': '''
        adjustments battery beaker bug calculator chart circle-stack cloud code
        cog command-line computer-desktop cpu-chip cube device divide equals funnel
        hashtag presentation qr-code server signal slash table-cells variable
        wifi wrench
    ''',
    'status': '''
        bolt check clock exclamation eye finger-print flag information-circle key
        lifebuoy lock minus no-symbol plus power question-mark-circle shield x
    ''',
    'everyday': '''
        academic-cap banknotes briefcase building cake calendar credit-card
        currency fire gift globe light-bulb map moon percent-badge puzzle-piece
        receipt rocket-launch scale shopping sparkles star sun tag ticket trophy
        truck wallet
    ''',
}

_CATEGORY_BY_FAMILY = {
    family: category
    for category, families in HEROICON_FAMILIES.items()
    for family in families.split()
}


def heroicon_category(name):
    while name:
        if name in _CATEGORY_BY_FAMILY:
            return _CATEGORY_BY_FAMILY[name]
        name = name.rpartition('-')[0]
    return 'everyday'

# How to Add a New Episode Type

This guide describes every file you need to touch when adding a new episode type
(e.g. `'exam'`, `'lab'`, `'video'`).  Follow these steps in order.

---

## Checklist (N places to update)

| # | File | What to change |
|---|------|----------------|
| 1 | `courses/models.py` | Add the new type to `Episode.TYPE_CHOICES` |
| 2 | `courses/templatetags/course_filters.py` | Add display config to `EPISODE_TYPE_CONFIG` |
| 3 | `templates/courses/episodes/_tabs_<type>.html` | **Create** the learning-interface tabs include |
| 4 | `templates/courses/learning_interface.html` | Add an `{% elif %}` branch for the new type |
| 5 | `templates/teacher/episode_edit.html` | Add entry to `TYPE_CARD_VISIBILITY` JS object |
| 6 | Run `makemigrations` + `migrate` | Apply the DB schema change |

---

## Step-by-step

### 1. Model — `courses/models.py`

Add the new choice tuple to `Episode.TYPE_CHOICES`:

```python
TYPE_CHOICES = [
    ('material', 'Material'),
    ('quiz',     'Quiz'),
    ('code',     'Code'),
    ('paper',    'Paper'),
    # ('newexam',  'New Exam'),   ← example
]
```

If the new type uses `answer_pdf`, update its `help_text` accordingly.

### 2. Display config — `course_filters.py`

Add an entry to `EPISODE_TYPE_CONFIG`.  This dict controls the badge colour,
Bootstrap Icon, and human-readable label shown in every template:

```python
EPISODE_TYPE_CONFIG = {
    'material': {'badge': 'bg-primary', 'icon': 'bi-file-text',       'label': 'Material'},
    'quiz':     {'badge': 'bg-success', 'icon': 'bi-question-circle', 'label': 'Quiz'},
    'code':     {'badge': 'bg-info',    'icon': 'bi-code',            'label': 'Code'},
    'paper':    {'badge': 'bg-warning', 'icon': 'bi-file-earmark-pdf','label': 'Paper'},
    # 'newexam':  {'badge': 'bg-danger',  'icon': 'bi-pencil-square',   'label': 'Exam'},
}
```

- `badge` — Bootstrap background class (`bg-primary`, `bg-success`, …)
- `icon` — Bootstrap Icons class (`bi-file-text`, `bi-code`, …)
- `label` — Human-readable name

All templates that show episode icons (`learning_interface.html`,
`course_overview.html`, `course_edit.html`) read from this config via the
`episode_type_config` filter, so you **do not** need to update them separately.

### 3. Learning-interface tabs — `templates/courses/episodes/_tabs_<type>.html`

Create a new file named `_tabs_<type>.html` (e.g. `_tabs_exam.html`).

The file should contain a `<div class="card">` with:
- **Tab headers** (`card-header > ul.nav-tabs`) — at minimum the Info tab;
  optionally Material PDF and/or Answer PDF tabs.
- **Tab content** (`card-body > .tab-content`) — matching `.tab-pane` divs.

Copy an existing file (e.g. `_tabs_material.html`) as a starting point.

### 4. Learning interface — `learning_interface.html`

In the `{% if current_episode.type … %}` block, add a new branch:

```django
{% elif current_episode.type == 'newexam' %}
    {% include 'courses/episodes/_tabs_newexam.html' %}
```

### 5. Teacher edit form — `episode_edit.html`

The JS object `TYPE_CARD_VISIBILITY` controls which form cards are shown for
each type.  Three card IDs are available:

| Card ID | Description |
|---------|-------------|
| `episodeInfoCard` | Title & order (always visible) |
| `infoContentCard` | Markdown editor |
| `pdfFilesCard` | PDF uploads (content + answer) |

Add your type with the cards it needs:

```js
const TYPE_CARD_VISIBILITY = {
    material: { cards: ['episodeInfoCard', 'infoContentCard', 'pdfFilesCard'] },
    quiz:     { cards: ['episodeInfoCard', 'infoContentCard'] },
    code:     { cards: ['episodeInfoCard', 'infoContentCard'] },
    paper:    { cards: ['episodeInfo', 'pdfFilesCard'] },
    // newexam:  { cards: ['episodeInfoCard', 'pdfFilesCard'] },
};
```

When `pdfFilesCard` is present, both `content_pdf` **and** `answer_pdf` inputs
are enabled automatically.

### 6. Database migration

```bash
uv run python manage.py makemigrations
uv run python manage.py migrate
uv run python manage.py check
```

---

## Summary

| What | How many files |
|------|---------------|
| Model choice | 1 (`models.py`) |
| Display config | 1 (`course_filters.py`) |
| New tab include | 1 (new file) |
| Include branch | 1 (`learning_interface.html`) |
| Edit-form cards | 1 (`episode_edit.html`) |
| **Total files** | **5** |

Everything else (course overview, course edit list, sidebar icons, etc.) uses
the centralised `EPISODE_TYPE_CONFIG` and requires **no changes**.

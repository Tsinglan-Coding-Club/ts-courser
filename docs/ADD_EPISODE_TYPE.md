# Adding an Episode Type

Checked against the working tree on 2026-09-05. Current types are `material`, `quiz`, `code`, and `paper`. Adding a display-only lesson and adding a lesson with submissions have different scopes.

## Content and authoring checklist

| File | Change |
| --- | --- |
| `courses/models.py` | Add to `Episode.TYPE_CHOICES`; introduce any required content/settings fields |
| `courses/templatetags/course_filters.py` | Add badge, icon, and label to `EPISODE_TYPE_CONFIG` |
| `templates/courses/episodes/_tabs_<type>.html` | Create the learning layout, using a suitable existing tab include |
| `templates/courses/learning_interface.html` | Add the type include branch; check type-specific header actions and runtime initialization |
| `templates/teacher/episode_edit.html` | Update `TYPE_CARD_VISIBILITY`; add new cards to `ALL_TYPE_RELEVANT_CARDS` and wire their inputs |
| `teacher/views.py` | Check creation/edit validation, saved fields, and template context for the new type |
| `courses/views.py` | Supply the learning context needed by the new layout |
| `courses/migrations/` | Generate and inspect migrations for choices/field changes |

The current form cards are:

| Card | Purpose |
| --- | --- |
| `episodeInfoCard` | Episode title/type; ordering is managed on the course editor |
| `infoContentCard` | Markdown information |
| `pdfFilesCard` | Content and answer PDF uploads |
| `quizEditorCard`, `quizConfigCard` | Visual quiz editor and submission/release options |
| `codeLayoutCard` | Interactive/reference panel visibility |
| `starterCodeCard` | Initial Python code |
| `codeOJCard` | Optional input/output test cases |
| `referenceSheetCard` | Markdown reference sheet |

Current visibility:

```js
const TYPE_CARD_VISIBILITY = {
    material: { cards: ['episodeInfoCard', 'infoContentCard', 'pdfFilesCard'] },
    quiz: { cards: ['episodeInfoCard', 'quizEditorCard', 'quizConfigCard'] },
    code: { cards: ['episodeInfoCard', 'infoContentCard', 'codeLayoutCard', 'starterCodeCard', 'codeOJCard', 'referenceSheetCard'] },
    paper: { cards: ['episodeInfoCard', 'pdfFilesCard'] },
};
```

`pdfFilesCard` enables both PDF inputs. Explicitly decide which files the new student layout displays and which the server accepts; hiding a field is not server validation. Existing icon consumers use `episode_type_config`, so they usually need no separate badge changes.

## If the type accepts student work

Check these additional responsibilities instead of assuming all episode types automatically support submissions:

- `progress/models.py`, `progress/views.py`, and `progress/urls.py`: storage, submission validation, enrollment/type checks, and read-status semantics.
- `teacher/views.py`: `course_manage` currently lists only quiz/code assignments; `assignment_review` has type-specific review logic.
- `templates/teacher/course_manage.html` and `assignment_review.html`: assignment lists, detail rendering, and review actions.
- Student tab and learning header: save/submit behavior, pending state, and released results.

Define whether work is a draft or formal submission, whether attempts are retained, how feedback is released, and what counts as completion. Add regression coverage for those rules and unauthorized/cross-course requests.

## Quiz-format changes are a separate workflow

Adding a quiz question type does not necessarily require a new Episode type. Update:

1. `static/js/quiz-editor.js`: question metadata, parser, serializer, editor controls.
2. `courses/quiz.py`: canonical parser, answer validation, student-safe question projection, and review normalization.
3. `templates/courses/episodes/_tabs_quiz.html`: structured-data rendering, answer collection, and results.
4. `teacher/views.py` and `templates/teacher/assignment_review.html`: correctness/review and any new teacher actions.
5. Relevant Python/JavaScript tests for authoring round-trips, required answers, answer-key exclusion, and review.

The student template no longer parses raw quiz Markdown. The teacher view imports the parser from `courses/quiz.py`. Preserve fenced-code handling and CBA token/solution separation.

## Validation

```bash
uv run python manage.py makemigrations
uv run python manage.py migrate
uv run python manage.py check
uv run python manage.py test courses progress teacher
npm test
```

For runtime/library changes also run `uv run python -m unittest discover -s tests`. Verify the new type through teacher creation/editing, published-course student access, navigation, refresh, and any submission/review cycle. See [CLAUDE.md](../CLAUDE.md) for release checks and conventions.

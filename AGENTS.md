# Repository Guidelines

TS-Courser is a Django learning platform with three roles (students, teachers, admins), course progress tracking, quizzes, and a code runner. The current contributor guide lives in [CLAUDE.md](/Users/qizhengwang/Desktop/school/12/ts-courser/CLAUDE.md); this file summarizes the essentials.

## Project Structure & Module Organization

- `ts_courser/` — settings, root URL routing, middleware, and shared utilities.
- `accounts/`, `courses/`, `progress/`, `teacher/` — Django apps for auth/users, course content, student progress/submissions, and teacher management.
- `templates/` — project-level Django templates, grouped by app. Episode tabs live in `templates/courses/episodes/`.
- `static/` — CSS and JavaScript; `node_modules/` supplies Monaco Editor and Pyodide.
- `docs/` — workflow guides such as `ADD_EPISODE_TYPE.md`; `reference/` holds Pyodide notes.

## Build, Test, and Development Commands

Use `uv`, not `pip` or `poetry`.

- `uv sync` — install/sync Python dependencies.
- `uv run python manage.py runserver` — start the dev server.
- `uv run python manage.py migrate` — apply database migrations.
- `uv run python manage.py makemigrations` — generate migrations after model changes.
- `uv run python manage.py check` — validate project configuration.
- `uv run python manage.py createsuperuser` — create an admin account.

## Coding Style & Naming Conventions

- Follow PEP 8 and Django conventions; use 4-space indentation.
- Name models with `PascalCase`, functions/views/variables with `snake_case`, and apps with short lowercase names.
- Keep templates in `templates/<app>/...` and static assets in `static/<type>/...`.
- No formatter or linter is configured, so keep changes consistent with surrounding files.

## Testing Guidelines

- Tests use Django's `TestCase` and live in each app's `tests.py`.
- Name test methods descriptively, e.g. `test_formal_submission_promotes_uploaded_code`.
- Run all tests with `uv run python manage.py test`; target one app with `uv run python manage.py test progress`.
- Add tests for new views and business logic. App coverage also includes `test_release.py`; run standalone Python tests with `uv run python -m unittest discover -s tests` and JavaScript tests with `npm test`.

## Commit & Pull Request Guidelines

- Use Conventional Commit prefixes such as `feat:`, `fix:`, `docs:`, `chore:`, and `refactor:` (see `git log`).
- Open PRs from feature branches named `feat/<topic>`; describe the change, link related issues, and include screenshots for UI changes.
- Keep migrations in the PR and note any manual deployment steps, such as a production `SECRET_KEY` change.

## Quiz Format Synchronization

Quiz Markdown authoring/parsing lives in `static/js/quiz-editor.js` and the canonical server module `courses/quiz.py`. The student template `templates/courses/episodes/_tabs_quiz.html` receives structured question data; `teacher/views.py` imports the server parser. Keep editor serialization, server validation/projection, student rendering, and teacher review synchronized for format changes, including CBA questions. Follow `docs/ADD_EPISODE_TYPE.md` for new episode types.

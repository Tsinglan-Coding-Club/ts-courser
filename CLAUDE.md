# Contributor Guide

Implementation guidance for TS-Courser, checked against the working tree on 2026-09-05. Start with [README.md](README.md) for capabilities, setup, limitations, and the documentation index. Use `uv` for Python dependencies and commands.

## Stack and layout

Django (locked version in `uv.lock`), SQLite, Python 3.13+, Django templates, Bootstrap 5, native Fetch, Vditor, marked.js, PDF.js, Monaco, and Pyodide. JavaScript ES modules and the Python `courser` library support the code lesson runtime.

- `accounts/`: custom `User`, authentication, profiles, and user administration.
- `courses/`: `Tag → Course → Section → Episode` content and learning views; `courses/quiz.py` owns server-side quiz parsing, student projections, and answer validation.
- `progress/`: enrollment, last position, read status, quiz/code records, and submission APIs.
- `teacher/`: course authoring, ownership decorators, ordering, student management, and review.
- `templates/<app>/`: project-level templates. Episode layouts are in `templates/courses/episodes/`.
- `static/js/`: quiz authoring, runtime/worker, input, error handling, interactive and reference rendering.
- `static/python/courser.py`: teaching display library. See [INTERACTIVE_AREA.md](docs/INTERACTIVE_AREA.md).
- `ts_courser/`: settings, root routes, middleware, context processors, and upload utilities.

## Commands and validation

```bash
uv sync
npm install
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

Bare `runserver` uses port 8712; an explicit port overrides it. Do not create migrations during ordinary installation. After model changes, generate and inspect migrations with `uv run python manage.py makemigrations`, then apply them.

```bash
uv run python manage.py check
uv run python manage.py test
npm test
uv run python -m unittest discover -s tests
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py collectstatic --noinput --dry-run
```

Django tests live in app `tests.py` and `test_release.py` modules. Standalone Python tests require separate discovery; JavaScript tests live in `static/js/tests/`. Use the relevant subset during development, and the CI checks for release work. Production checks and environment setup are documented in [DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Accounts and ownership

`accounts.User` extends `AbstractUser` without changing `USERNAME_FIELD`. Local login uses administrator-issued usernames and passwords; email is optional and is never an identity key. Public registration is disabled. Microsoft sign-in uses the fixed school tenant and an `ExternalIdentity` keyed by `(provider, tenant_id, object_id)`. Never auto-link accounts by email or UPN.

Local accounts require `local_login_enabled=True`. Single-student creation takes an administrator-supplied username and initial password. Bulk creation accepts a table of English names or pinyin and one shared initial password for up to 200 students. `accounts.services` derives lowercase ASCII usernames from names, simplifies accents, removes spaces/punctuation, and adds numeric suffixes for existing or within-batch collisions. A signed, administrator-bound preview fixes the names and usernames for ten minutes; creation rechecks availability and commits the entire batch atomically. Passwords are never generated, and simple initial passwords are allowed for classroom use.

Newly issued students keep their assigned username and must change their password through the short pre-authentication flow before a normal Django session is created; new passwords still pass Django password validation. Newly issued local administrators must change both username and password. Microsoft-only users have unusable local passwords. Pending Microsoft teachers are confined by `AccountStateMiddleware` until an administrator approves them.

Current role properties:

- `is_student`: `role == 'student'`.
- `is_teacher`: teacher role plus `is_verified_teacher`.
- `is_admin`: admin role or Django superuser. `is_staff` controls Django-admin access only and must not grant platform-wide course permissions.

Teacher mutations use `@login_required`, `@teacher_required`, and the applicable course permission decorator. CourseTeacherMembership grants view, edit, or manage; course creation grants the creator an ordinary manage membership. The creator field is provenance and never an access bypass. Managers can change/remove any membership while retaining at least one manager. Review reads require view, grading/comments/release and content edits require edit, and teacher access administration requires manage. `require_course_ownership` injects `request.course`; `require_episode_ownership` injects both `request.episode` and `request.course`. Admins bypass course membership checks. `check_section_ownership` supplies the same check for section operations.

Student submission/progress access is centralized in `progress.views._get_accessible_episode`. Published-course learning views also enforce enrollment, with a teacher/admin bypass. Open-mode auto-enrollment requires `enrollment_open=True`; closing enrollment leaves existing enrollments intact. Current learning views require publication even for teachers; do not assume an unpublished student-preview route exists.

## Content and persistence

`Course` owns tags, publication, enrollment mode/code/open flag, and the inherited quiz release default. Code enrollment is the model default; codes are eight uppercase hexadecimal characters.

`Section` and `Episode` order by `(order, id)`. Creation appends to the parent. Drag-and-drop sorting is owned by the course editor and checked on the server. Do not reintroduce episode order fields in the episode form.

Episode types are `material`, `quiz`, `code`, and `paper`. Shared fields include Markdown information and PDFs. Quiz configuration is `quiz_require_all` and `quiz_release_policy`; `quiz_show_results` is a legacy field. Code configuration includes `starter_code`, `code_oj_enabled`, JSON test cases, `show_interactive`, `show_reference`, and `reference_sheet_content`. The default starter code is defined by `DEFAULT_STARTER_CODE` in `courses/models.py`.

Progress records:

| Model | Meaning |
| --- | --- |
| `CourseEnrollment` | One user/course enrollment |
| `UserProgress` | One user/course current episode |
| `EpisodeReadStatus` | One user/episode read flag; not a mastery grade |
| `QuizSubmission` | One user/episode latest answer JSON, FRQ grade JSON, question comment JSON, submission and release timestamps |
| `CodeSubmission` | One user/episode latest code, test-result JSON, upload timestamp, formal submission flag and timestamp |
| `CodeSubmissionHistory` | Full code/test-result snapshot for each formal submit; uploads do not create versions |

Code has submitted-version history. Quiz has no attempt history or question-version snapshot. Changing live questions can affect interpretation of previous answers; preserve this distinction when designing new functionality.

## Quiz authoring, delivery, and review

Supported question types: MCQ, MRQ, FRQ, SRT, and CBA (code assembly).

Questions start with `## ` outside fenced code. Ordinary answer markers are `>+` (single correct), `>*` (multiple correct), `>N` (sorting position), and `>=` (FRQ reference). A question without choices or with a single empty choice is FRQ. Ordinary unmarked choices use the existing first-choice fallback. CBA uses a `quiz-cba` fence and optional `quiz-cba-config` fence; preserve fence-aware parsing and editor serialization when modifying this format.

The current integration points are:

| File | Responsibility |
| --- | --- |
| `static/js/quiz-editor.js` | Teacher `parseQuiz` / `serializeQuiz` and visual authoring |
| `courses/quiz.py` | Canonical Python parser, `student_questions`, `validate_answers`, `review_answers`, and CBA token projection |
| `templates/courses/episodes/_tabs_quiz.html` | Student rendering/submission/results from structured question data; no duplicate raw-Markdown parser |
| `teacher/views.py` | Imports the Python parser; objective review and FRQ grading/release |

Unreleased student data must omit answer keys, FRQ references, and CBA solution positions. Keep server validation, editor round-trips, and student/review rendering consistent when changing question formats. Add appropriate Python and JavaScript regression coverage, including fenced content and CBA cases.

Release behavior in `progress.views.submit_quiz`:

- `immediate`: release on submission, including FRQs.
- `manual`: teacher release required.
- `inherit`: automatic only when the course enables it and the quiz contains no FRQ.

Changed answers clear previous FRQ grades and question comments and recalculate release status; identical answers retain existing review state. Teacher grade/release/cancel/reset actions require the `submission_version` timestamp to match, returning 409 for stale requests. Manual release requires every FRQ to have a boolean grade. FRQ grades store `{question_index: is_correct}` without partial credit. `question_comments` separately stores plain-text feedback keyed by question index for all question types. Feedback follows result release and uses the same stale-submission guard as grading.

## Python execution and submissions

Monaco and Pyodide assets come from `node_modules/`. Python runs in a browser worker, with SharedArrayBuffer-backed input/interrupt support. Preserve the COOP/COEP behavior in middleware, development WSGI static handling, and production static serving. Interactive display details and limits belong in [INTERACTIVE_AREA.md](docs/INTERACTIVE_AREA.md).

Editor initialization prefers a usable local draft, then server code, then teacher starter code. Automatic saves are local-only (every 60 seconds). Upload calls `/api/code/upload/` and sets `is_submitted=False`; formal submission calls `/api/code/submit/` and makes the record visible for review. A later upload overwrites that latest record and clears its submission state, but leaves CodeSubmissionHistory snapshots intact and available to teachers. Every successful formal submit appends a full snapshot, including repeated code. Restoring history loads code into the editor as a draft and requires a separate submit to create another version.

`progress/validation.py` validates browser test-result structure and provides tolerant handling for legacy stored results. The server does not run student Python or verify correctness independently.

## Uploads and request conventions

Use the shared image utilities in `ts_courser/utils.py`: raster decoding/re-encoding, size/pixel limits, and server-determined extensions. Invalid images are rejected. PDF validation is in `teacher.views.validate_pdf`, with libmagic, header validation, and a 50 MB limit. PDFs use UUID-based names under `media/episode_pdfs/` or `media/answer_pdfs/`.

Project AJAX endpoints normally return `{'success': True/False}`. Vditor image upload `/api/upload/` requires its own `{'code': 0, 'data': {'succMap': {...}}}` schema. Fetch mutations need CSRF tokens. Routes are defined in each app's `urls.py`; progress routes are mounted under `/api/`.

## Change workflow

Follow PEP 8/Django conventions and surrounding template/JavaScript style. Add or adjust models, migrations, validation, views, routes, and templates together where applicable. New views and business logic need regression tests. See [ADD_EPISODE_TYPE.md](docs/ADD_EPISODE_TYPE.md) before introducing a lesson type.

Use Conventional Commit prefixes and `feat/<topic>` feature branches. Include relevant validation and UI screenshots in PRs. Keep existing uncommitted work intact. Design documents and historical review reports do not establish that a feature has shipped; current limitations are indexed in the README.

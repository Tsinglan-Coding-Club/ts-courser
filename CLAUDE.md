# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TS-Courser is a Django-based online learning platform (MVP stage) inspired by Khan Academy. It supports three user roles (students, teachers, admins) with course browsing, content management, progress tracking, enrollment, and interactive quizzes (MCQ, MRQ, FRQ, sorting).

## Tech Stack

- **Backend**: Django 5.x with SQLite database
- **Package Manager**: uv (not pip/poetry)
- **Frontend**: Bootstrap 5, native Fetch API (no jQuery)
- **Markdown**: Vditor editor (teacher side), marked.js (student side)
- **PDF**: PDF.js for viewing
- **Image Processing**: Pillow for image compression
- **Custom User Model**: `accounts.User` (email-based login with role field)

## Development Commands

### Environment Setup
```bash
# Install/sync dependencies
uv sync

# Create/apply database migrations
uv run python manage.py makemigrations
uv run python manage.py migrate

# Create admin account
uv run python manage.py createsuperuser
```

### Running the Server
```bash
# Development server
uv run python manage.py runserver

# With custom port
uv run python manage.py runserver 8080
```

### Database Management
```bash
# Open Django shell
uv run python manage.py shell

# Reset database (careful!)
# Delete db.sqlite3 file, then run migrate again
```

### Testing & Debugging
```bash
# Run tests
uv run python manage.py test

# Check for issues
uv run python manage.py check
```

## Project Structure

```
ts_courser/              # Main Django project settings
├── settings.py          # INSTALLED_APPS: accounts, courses, progress, teacher
├── urls.py              # Root URL configuration
├── wsgi.py
├── utils.py             # Shared utilities: image compression (Pillow)
├── middleware.py        # CrossOriginIsolationMiddleware
└── context_processors.py

accounts/                # User authentication & authorization
├── models.py            # User model with role/profile/email-verification fields
├── views.py             # Registration, login, logout, profile, favorite tags
└── urls.py              # app_name: 'accounts'

courses/                 # Course browsing & learning interface
├── models.py            # Tag, Course, Section, Episode models
├── views.py             # Course list, overview, dashboard, learning interface
├── templatetags/        # Custom template filters (basename, episode_type_config)
│   └── course_filters.py
└── urls.py              # app_name: 'courses'

progress/                # Student progress, enrollment, quiz submissions
├── models.py            # UserProgress, EpisodeReadStatus, CourseEnrollment, QuizSubmission
├── views.py             # AJAX endpoints for progress, enrollment, uploads, quiz submit, My Courses
└── urls.py              # app_name: 'progress' (mounted at /api/)

teacher/                 # Teacher content management & assignment review
├── views.py             # CRUD for courses/sections/episodes, reorder, tags, quiz grading
├── urls.py              # app_name: 'teacher'
└── decorators.py        # Three-layer permission decorators + check_section_ownership helper

static/
└── js/
    └── quiz-editor.js   # Quiz markdown parser, serializer, and visual editor UI

templates/               # Django templates (project-level, not in app directories)
├── base.html
├── accounts/
├── courses/
│   ├── course_list.html
│   ├── course_overview.html      # Pre-enrollment landing page
│   ├── course_dashboard.html     # Enrolled student hub
│   ├── learning_interface.html
│   └── episodes/
│       └── _tabs_quiz.html       # Quiz tab: question rendering, submission, results
├── progress/
└── teacher/
    ├── course_list.html
    ├── course_edit.html           # Course settings + section/episode management
    ├── course_manage.html         # Student progress, management, assignments tabs
    ├── episode_edit.html          # Episode editor with quiz editor integration
    └── assignment_review.html     # Teacher quiz grading & release interface
```

## Key Architecture Patterns

### User Model & Permissions

- Custom User model extends `AbstractUser` with `role` field ('student'/'teacher'/'admin')
- Teachers need `is_verified_teacher=True` to access teacher features
- Properties: `is_student`, `is_teacher`, `is_admin` for permission checks
- Email is used for login (unique field); email verification via 6-digit code (MVP: printed to console)
- Profile fields: `display_name`, `bio`, `avatar`, `favorite_tags` (M2M to Tag)

### Teacher Authorization (Three-Layer System)

Defined in `teacher/decorators.py`:

1. **`@teacher_required`** — user must be verified teacher or admin; raises PermissionDenied otherwise
2. **`@require_course_ownership`** — course must belong to user (admin bypass); injects `request.course`
3. **`@require_episode_ownership`** — episode's parent course must belong to user (admin bypass); injects `request.episode` and `request.course`

Also available as an imperative helper:
- **`check_section_ownership(request, section_id)`** — returns `(section, course)` tuple or raises PermissionDenied

These decorators must be stacked in order: `@login_required` → `@teacher_required` → `@require_course_ownership`. Admin users bypass all ownership checks.

### Course Content Hierarchy

```
Course (has creator, tags, is_published, enrollment controls)
├── thumbnail (ImageField, compressed via Pillow)
├── enrollment_mode: 'open' or 'code'
├── course_code: auto-generated 8-char code (secrets.token_hex)
├── enrollment_open: boolean toggle
├── auto_release_results: boolean toggle (course-level quiz auto-release)
└── Section (ordered by 'order' field, drag-and-drop reorderable)
    └── Episode (ordered by 'order' field, drag-and-drop reorderable)
        ├── type: 'material', 'quiz', 'code', or 'paper'
        ├── info_page_content (markdown text; for quiz: quiz markdown format)
        ├── content_pdf (main content)
        ├── answer_pdf (paper type only)
        ├── quiz_require_all (must answer all questions before submit)
        ├── quiz_show_results (show results immediately after submission)
        ├── show_interactive (code episodes: show interactive panel)
        └── show_reference (code episodes: show reference panel)
```

### Course Enrollment System

- **`CourseEnrollment`**: One per user-course pair, tracks enrollment date (`enrolled_at`)
- Enrollment modes:
  - **Open** (`enrollment_mode='open'`): Auto-enroll when accessing learning interface
  - **Code** (`enrollment_mode='code'`): Requires entering the 8-char `course_code`
- `enrollment_open` boolean toggles whether new enrollments are accepted
- Teachers/admins bypass enrollment check on the learning interface
- Enrollment controlled via `/api/enroll/` and `/api/unenroll/` AJAX endpoints
- Enrolled students are redirected from the overview page to the course dashboard

### Progress Tracking

- **`UserProgress`**: One per user-course pair, tracks `current_episode`
- **`EpisodeReadStatus`**: One per user-episode pair, tracks `is_read` boolean
- AJAX endpoints (`/api/progress/update/`, `/api/progress/mark/`) handle real-time updates
- Quiz submission automatically marks the episode as read

### Quiz System

The quiz system supports four question types defined via a custom markdown format:

- **MCQ** (Multiple Choice): Single correct answer — `>+` marker
- **MRQ** (Multi-Response): Multiple correct answers — `>*` marker
- **FRQ** (Free Response): Text answer with optional reference answer — `>=` marker
- **SRT** (Sorting): Drag-and-drop ordering — `>N` position marker

#### Quiz Markdown Format

Questions are separated by `## ` (h2) at line start. Question text spans everything before the first `>` choice line.

```
## What is 2+2?
Here is some **explanation** with `code`.
>+ 4
> 3
> 5

## Which are prime numbers? (MRQ)
>* 2
>* 3
> 4
>* 5

## Explain Newton's First Law.
Use **markdown** in your response.
>

## Sort by size, smallest first
>1 Seed
>3 Watermelon
>2 Apple
>4 Pumpkin

## FRQ with reference answer
>= The force acting on an object is equal to its mass times acceleration.
```

#### Quiz Submission & Review Flow

1. **Student takes quiz**: Questions rendered one-at-a-time with navigation. Answers stored in JS.
2. **Submission**: Both tab button and header button call shared `window.submitQuiz()`. Payload is `{questions: [{type, selectedIndex/selectedIds/text}]}`.
3. **Auto-release logic** (in `submit_quiz` view):
   - If `episode.quiz_show_results=True` → immediate release (even with FRQ)
   - Else if `course.auto_release_results=True` and no FRQ questions → immediate release
   - Otherwise → `released_at=None` (teacher must manually review and release)
4. **Teacher review**: Assignment review page shows all submissions with auto-graded MCQ/MRQ/SRT correctness. FRQ answers require manual grading (Correct/Incorrect).
5. **Release**: Teacher releases graded submission → student sees results with correct/incorrect highlights.
6. **Resubmission**: Preserves existing manual release if auto-release conditions aren't met.

#### Quiz Parsers (three implementations — must stay in sync)

| Location | Function | Purpose |
|----------|----------|---------|
| `static/js/quiz-editor.js` | `parseQuiz()` / `serializeQuiz()` | Teacher-side visual editor |
| `templates/courses/episodes/_tabs_quiz.html` | inline `parseQuiz()` | Student-side question rendering & results |
| `teacher/views.py` | `_parse_quiz_markdown()` | Teacher-side assignment review |

All three parsers must handle: "None" skip, auto-correct-first-choice fallback, `isFRQRef` detection, and all four question type markers.

#### Quiz Editor (`static/js/quiz-editor.js`)

- `parseQuiz(markdown)` → `[{id, type, question, choices, refAnswer}]`
- `serializeQuiz(questions)` → markdown string
- `initQuizEditor(config)` → attaches visual editor to DOM (source textarea + preview panel)
- Exposed globally as `window.QuizEditor`
- Supports drag-and-drop reordering of questions and choices
- Type switching (MCQ ↔ MRQ ↔ SRT ↔ FRQ) with appropriate data migration
- Image upload via Vditor endpoint for inline images in question text

### Content Reordering

- Sections and episodes support drag-and-drop reordering via AJAX endpoints
- `/teacher/sections/reorder/` and `/teacher/episodes/reorder/` accept JSON bodies with `{section_orders: [{id, order}]}` / `{episode_orders: [{id, order}]}`
- Ownership verified before reorder is applied

### Image Compression

- `ts_courser.utils.compress_image()` compresses images > 1MB to JPEG (80% quality) via Pillow
- Handles transparency by compositing onto white background
- Used for course thumbnails, user avatars, and Vditor image uploads
- Returns original file on error or if compressed version isn't smaller

### File Upload Strategy

- PDFs uploaded to `media/episode_pdfs/` or `media/answer_pdfs/`
- Filenames: `{uuid}_{instance_id}.{ext}` for uniqueness
- MIME type validation with `python-magic` library plus PDF header check (magic number `%PDF`)
- PDF size limit: 50MB (validated in `teacher/views.py:validate_pdf`)
- Upload endpoint `/api/upload/` for Vditor image uploads
- Vditor upload uses `{'code': 0, 'data': {'succMap': {...}}}` format (Vditor-specific, NOT the project-standard `{'success': True}`)

### Frontend-Backend Communication

- **AJAX with Fetch API**: Progress updates, read status toggle, enrollment, reordering, quiz submit, FRQ grading
- **CSRF tokens**: Required for POST requests (included in templates)
- **JSON responses**: Standard format is `{'success': True/False}` for project endpoints; Vditor upload uses `{'code': 0}` format
- **Quiz data flow**: Quiz answers collected in JS → serialized as JSON → submitted via FormData → stored in QuizSubmission.answers TextField → parsed back for review/results display.

## URL Patterns

```
/                                    → Redirects to course list
/accounts/register/                  → Registration with email verification
/accounts/login/                     → Login
/accounts/logout/                    → Logout
/accounts/profile/                   → Own profile
/accounts/profile/edit/              → Edit profile (avatar, display name, bio, tags)
/accounts/profile/<username>/        → View another user's profile
/accounts/api/send-verification-code/ → AJAX: Send email verification code
/accounts/api/update-favorite-tags/  → AJAX: Update user's favorite tags
/courses/                            → Course list (with tag filters)
/courses/<id>/overview/              → Course overview (pre-enrollment landing page)
/courses/<id>/dashboard/             → Enrolled student hub (progress, content, continue)
/courses/<id>/learn/                 → Learning interface (redirects to last episode)
/courses/<id>/learn/<eid>/           → Specific episode view
/teacher/courses/                    → Teacher course management (own courses only)
/teacher/courses/create/             → Create new course
/teacher/courses/<id>/edit/          → Edit course (sections, episodes, enrollment)
/teacher/courses/<id>/manage/        → Manage students, progress stats, assignments
/teacher/courses/<id>/delete/        → Delete course (POST only, cascade)
/teacher/courses/remove-student/     → AJAX: Remove student from course
/teacher/sections/create/            → Create section
/teacher/sections/<id>/delete/       → Delete section
/teacher/sections/reorder/           → AJAX: Drag-and-drop section reorder
/teacher/episodes/create/            → Create episode
/teacher/episodes/<id>/edit/         → Edit episode (quiz editor for quiz type)
/teacher/episodes/<id>/delete/       → Delete episode
/teacher/episodes/reorder/           → AJAX: Drag-and-drop episode reorder
/teacher/tags/create/                → AJAX: Create new tag
/teacher/courses/<id>/assignments/<eid>/ → Review quiz submissions for an episode
/teacher/assignments/grade-frq/      → AJAX: Grade a FRQ answer
/teacher/assignments/release/        → AJAX: Release submission to student
/teacher/assignments/cancel-release/ → AJAX: Cancel a release
/teacher/assignments/reset/          → AJAX: Reset submission (student can redo)
/api/progress/update/                → AJAX: Update current episode
/api/progress/mark/                  → AJAX: Toggle read/unread
/api/upload/                         → AJAX: Vditor image upload
/api/enroll/                         → AJAX: Enroll in course (with optional code)
/api/unenroll/                       → AJAX: Unenroll from course
/api/quiz/submit/                    → AJAX: Submit quiz answers
/api/my-courses/                     → "My Courses" page (enrolled courses with progress)
/admin/                              → Django admin panel
```

## Database Models Reference

### Core Models
- **User**: role, email (login), is_verified_teacher, display_name, bio, avatar, favorite_tags (M2M→Tag), is_email_verified, email_verification_code
- **Tag**: name (unique), category ('track'/'subject')
- **Course**: title, description, thumbnail, creator (FK→User), tags (M2M→Tag), is_published, enrollment_mode, course_code, enrollment_open, auto_release_results
- **Section**: course (FK→Course, related_name='sections'), title, order
- **Episode**: section (FK→Section, related_name='episodes'), title, type ('material'/'quiz'/'code'/'paper'), order, info_page_content, content_pdf, answer_pdf, quiz_require_all, quiz_show_results, show_interactive, show_reference

### Progress/Enrollment Models
- **CourseEnrollment**: user (FK→User), course (FK→Course), enrolled_at — unique_together=[user, course]
- **UserProgress**: user (FK→User), course (FK→Course), current_episode (FK→Episode, SET_NULL) — unique_together=[user, course]
- **EpisodeReadStatus**: user (FK→User), episode (FK→Episode), is_read — unique_together=[user, episode]
- **QuizSubmission**: user (FK→User), episode (FK→Episode), answers (TextField, JSON), frq_grades (TextField, JSON), submitted_at, released_at — unique_together=[user, episode]

### Important Relations
- `Course.sections` (related_name on Section)
- `Section.episodes` (related_name on Episode)
- `User.created_courses` (courses created by user)
- `User.course_progress` (progress records for user)
- `User.enrolled_courses` (CourseEnrollment records)
- `User.quiz_submissions` (QuizSubmission records)
- `User.favorite_tags` (M2M to Tag)
- `Episode.course` — property that returns `self.section.course`
- `Episode.submissions` — related_name on QuizSubmission

## Common Workflows

### Adding a New Feature
1. Create/modify models in appropriate app
2. Run `makemigrations` and `migrate`
3. Update views.py with business logic
4. Create/update templates in `templates/` directory
5. Add URL patterns to app's urls.py
6. Test with runserver

### Debugging Template Issues
- Templates are in project-level `templates/` directory (not inside app directories)
- Template context includes: user (from auth), messages (from Django messages framework)
- Media files accessed via `{{ MEDIA_URL }}` in templates
- Version string available via `{{ VERSION }}` context variable

### Working with Vditor
- Vditor is initialized in teacher episode edit template
- Image uploads go through `/api/upload/` endpoint
- Upload response format MUST be `{'code': 0, 'data': {'succMap': {url: url}}}` — Vditor requires this exact schema
- Content saved as markdown in `Episode.info_page_content`
- Students see rendered HTML via marked.js

### Working with the Quiz Editor
- Quiz editor is initialized when episode type is 'quiz' in `episode_edit.html`
- Editor syncs bidirectionally: source textarea ↔ visual preview
- Content is saved to `mdEditor` (the canonical `info_page_content` field) on form submit
- When switching episode types, content is synced between quiz editor and mdEditor
- The `quiz-editor.js` module is loaded via `<script src="{% static 'js/quiz-editor.js' %}">`
- Quiz markdown toolbar supports bold, italic, strikethrough, lists, links, images, code blocks

### Adding a New Quiz Question Type
1. Add the type to `QUESTION_TYPES` in `quiz-editor.js` with `label`, `badgeClass`, `hasChoices`, `isSorting`
2. Update `parseQuiz()` with new marker pattern and type detection
3. Update `serializeQuiz()` with serialization logic
4. Update the inline `parseQuiz()` in `_tabs_quiz.html`
5. Update `_parse_quiz_markdown()` in `teacher/views.py`
6. Add rendering in the quiz tab JS (`renderQuestion` + results mode)
7. Add review display in `assignment_review.html` and the Python view
8. Add CSS for any new UI elements

## Important Notes

- This is an MVP project — email verification prints codes to console instead of sending emails
- Use `uv` commands, not `pip` or `poetry`
- CSRF tokens required for all POST requests
- File uploads need MIME validation (handled by `python-magic`); PDFs also check the `%PDF` header
- PDF size limit: 50MB
- Drag-and-drop reordering implemented for sections and episodes via AJAX endpoints
- Image compression via Pillow is used for thumbnails, avatars, and Vditor uploads — compress if > 1MB
- Project has static files from `node_modules/` (Monaco Editor, Pyodide) in STATICFILES_DIRS
- Teacher decorators inject `request.course` / `request.episode` — use these instead of re-querying
- Quiz parsers exist in three places and must be kept in sync — changes to the quiz format require updates to all three
- Quiz data is stored as raw markdown in `Episode.info_page_content` and as JSON in `QuizSubmission.answers`
- The `frq_grades` field stores a JSON dict of `{question_index: is_correct}` for teacher-graded FRQ answers
- Resubmission preserves existing `released_at` if auto-release conditions aren't met (manual teacher release is sticky)

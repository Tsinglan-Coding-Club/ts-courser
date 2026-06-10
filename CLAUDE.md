# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TS-Courser is a Django-based online learning platform (MVP stage) inspired by Khan Academy. It supports three user roles (students, teachers, admins) with course browsing, content management, progress tracking, and enrollment features.

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
├── views.py             # Course list, overview, learning interface
└── urls.py              # app_name: 'courses'

progress/                # Student progress & enrollment tracking
├── models.py            # UserProgress, EpisodeReadStatus, CourseEnrollment
├── views.py             # AJAX endpoints for progress, enrollment, uploads, My Courses
└── urls.py              # app_name: 'progress' (mounted at /api/)

teacher/                 # Teacher content management
├── views.py             # CRUD for courses/sections/episodes, reorder, tags
├── urls.py              # app_name: 'teacher'
└── decorators.py        # Three-layer permission decorators

templates/               # Django templates (project-level, not in app directories)
├── base.html
├── accounts/
├── courses/
├── progress/
└── teacher/
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

These decorators must be stacked in order: `@login_required` → `@teacher_required` → `@require_course_ownership`. Admin users bypass all ownership checks.

### Course Content Hierarchy

```
Course (has creator, tags, is_published, enrollment controls)
├── thumbnail (ImageField, compressed via Pillow)
├── enrollment_mode: 'open' or 'code'
├── course_code: auto-generated 8-char code (SHA-256 hash)
├── enrollment_open: boolean toggle
└── Section (ordered by 'order' field, drag-and-drop reorderable)
    └── Episode (ordered by 'order' field, drag-and-drop reorderable)
        ├── type: 'material', 'quiz', 'code', or 'paper'
        ├── info_page_content (markdown text)
        ├── content_pdf (main content)
        ├── answer_pdf (quiz/paper answers)
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

### Progress Tracking

- **`UserProgress`**: One per user-course pair, tracks `current_episode`
- **`EpisodeReadStatus`**: One per user-episode pair, tracks `is_read` boolean
- AJAX endpoints (`/api/progress/update/`, `/api/progress/mark/`) handle real-time updates

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
- Upload endpoint `/api/upload/` for Vditor image uploads
- Vditor upload uses `{'code': 0, 'data': {'succMap': {...}}}` format (Vditor-specific, NOT the project-standard `{'success': True}`)

### Frontend-Backend Communication

- **AJAX with Fetch API**: Progress updates, read status toggle, enrollment, reordering
- **CSRF tokens**: Required for POST requests (included in templates)
- **JSON responses**: Standard format is `{'success': True/False}` for project endpoints; Vditor upload uses `{'code': 0}` format
- **Django forms**: Used for course/episode creation/editing

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
/courses/<id>/overview/              → Course overview with enrollment & progress
/courses/<id>/learn/                 → Learning interface (redirects to last episode)
/courses/<id>/learn/<eid>/           → Specific episode view
/teacher/courses/                    → Teacher course management (own courses only)
/teacher/courses/create/             → Create new course
/teacher/courses/<id>/edit/          → Edit course (sections, episodes, enrollment)
/teacher/courses/<id>/delete/        → Delete course (POST only, cascade)
/teacher/sections/create/            → Create section
/teacher/sections/<id>/delete/       → Delete section
/teacher/sections/reorder/           → AJAX: Drag-and-drop section reorder
/teacher/episodes/create/            → Create episode
/teacher/episodes/<id>/edit/         → Edit episode with Vditor markdown editor
/teacher/episodes/<id>/delete/       → Delete episode
/teacher/episodes/reorder/           → AJAX: Drag-and-drop episode reorder
/teacher/tags/create/                → AJAX: Create new tag
/api/progress/update/                → AJAX: Update current episode
/api/progress/mark/                  → AJAX: Toggle read/unread
/api/upload/                         → AJAX: Vditor image upload
/api/enroll/                         → AJAX: Enroll in course (with optional code)
/api/unenroll/                       → AJAX: Unenroll from course
/api/my-courses/                     → "My Courses" page (enrolled courses with progress)
/admin/                              → Django admin panel
```

## Database Models Reference

### Core Models
- **User**: role, email (login), is_verified_teacher, display_name, bio, avatar, favorite_tags (M2M→Tag), is_email_verified, email_verification_code
- **Tag**: name (unique), category ('track'/'subject')
- **Course**: title, description, thumbnail, creator (FK→User), tags (M2M→Tag), is_published, enrollment_mode, course_code, enrollment_open
- **Section**: course (FK→Course, related_name='sections'), title, order
- **Episode**: section (FK→Section, related_name='episodes'), title, type ('material'/'quiz'/'code'/'paper'), order, info_page_content, content_pdf, answer_pdf, show_interactive, show_reference

### Progress/Enrollment Models
- **CourseEnrollment**: user (FK→User), course (FK→Course), enrolled_at — unique_together=[user, course]
- **UserProgress**: user (FK→User), course (FK→Course), current_episode (FK→Episode, SET_NULL) — unique_together=[user, course]
- **EpisodeReadStatus**: user (FK→User), episode (FK→Episode), is_read — unique_together=[user, episode]

### Important Relations
- `Course.sections` (related_name on Section)
- `Section.episodes` (related_name on Episode)
- `User.created_courses` (courses created by user)
- `User.course_progress` (progress records for user)
- `User.enrolled_courses` (CourseEnrollment records)
- `User.favorite_tags` (M2M to Tag)
- `Episode.course` — property that returns `self.section.course`

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

## Important Notes

- This is an MVP project — email verification prints codes to console instead of sending emails
- Use `uv` commands, not `pip` or `poetry`
- CSRF tokens required for all POST requests
- File uploads need MIME validation (handled by `python-magic`); PDFs also check the `%PDF` header
- Drag-and-drop reordering implemented for sections and episodes via AJAX endpoints
- Image compression via Pillow is used for thumbnails, avatars, and Vditor uploads — compress if > 1MB
- Project has static files from `node_modules/` (Monaco Editor, Pyodide) in STATICFILES_DIRS
- Teacher decorators inject `request.course` / `request.episode` — use these instead of re-querying

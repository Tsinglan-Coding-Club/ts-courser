# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TS-Courser is a Django-based online learning platform (MVP stage) inspired by Khan Academy. It supports three user roles (students, teachers, admins) with course browsing, content management, and progress tracking features.

## Tech Stack

- **Backend**: Django 5.x with SQLite database
- **Package Manager**: uv (not pip/poetry)
- **Frontend**: Bootstrap 5, native Fetch API (no jQuery)
- **Markdown**: Vditor editor (teacher side), marked.js (student side)
- **PDF**: PDF.js for viewing
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
└── wsgi.py

accounts/                # User authentication & authorization
├── models.py            # User model with role/is_verified_teacher fields
└── views.py             # Registration, login, logout

courses/                 # Course browsing & learning interface
├── models.py            # Tag, Course, Section, Episode models
└── views.py             # Course list, overview, learning interface

progress/                # Student progress tracking
├── models.py            # UserProgress, EpisodeReadStatus
└── views.py             # AJAX endpoints for progress updates

teacher/                 # Teacher content management
└── views.py             # Course/section/episode creation & editing

templates/               # Django templates (not in app directories)
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
- Email is used for login (unique field)

### Course Content Hierarchy

```
Course (has creator, tags, is_published)
└── Section (ordered by 'order' field)
    └── Episode (ordered by 'order' field)
        ├── type: 'material' or 'quiz'
        ├── info_page_content (markdown text)
        ├── content_pdf (main content)
        └── answer_pdf (quiz answers only)
```

### Progress Tracking

- **UserProgress**: One per user-course pair, tracks `current_episode`
- **EpisodeReadStatus**: One per user-episode pair, tracks `is_read` boolean
- AJAX endpoints (`/api/progress/update/`, `/api/progress/mark/`) handle real-time updates

### File Upload Strategy

- PDFs uploaded to `media/episode_pdfs/` or `media/answer_pdfs/`
- Filenames: `{uuid}_{instance_id}.{ext}` for uniqueness
- MIME type validation with `python-magic` library
- Upload endpoint `/api/upload/` for Vditor image uploads

### Frontend-Backend Communication

- **AJAX with Fetch API**: Progress updates, read status toggle
- **CSRF tokens**: Required for POST requests (included in templates)
- **JSON responses**: Standard format for API endpoints
- **Django forms**: Used for course/episode creation/editing

## URL Patterns

```
/                         → Redirects to course list
/accounts/                → Registration, login, logout
/courses/                 → Course list (with tag filters)
/courses/<id>/overview/   → Course overview with progress
/courses/<id>/learn/      → Learning interface (redirects to last episode)
/courses/<id>/learn/<eid>/→ Specific episode view
/teacher/courses/         → Teacher course management
/teacher/episodes/<id>/edit/ → Episode editing with Vditor
/api/progress/update/     → AJAX: Update current episode
/api/progress/mark/       → AJAX: Toggle read/unread
/admin/                   → Django admin panel
```

## Database Models Reference

### Core Models
- **User**: role, email, is_verified_teacher
- **Tag**: name, category (track/subject)
- **Course**: title, description, creator, tags, is_published
- **Section**: course (FK), title, order
- **Episode**: section (FK), title, type, order, info_page_content, content_pdf, answer_pdf

### Progress Models
- **UserProgress**: user (FK), course (FK), current_episode (FK)
- **EpisodeReadStatus**: user (FK), episode (FK), is_read

### Important Relations
- Course.sections (related_name on Section)
- Section.episodes (related_name on Episode)
- User.created_courses (courses created by user)
- User.course_progress (progress records for user)

## Common Workflows

### Adding a New Feature
1. Create/modify models in appropriate app
2. Run `makemigrations` and `migrate`
3. Update views.py with business logic
4. Create/update templates in `templates/` directory
5. Add URL patterns to app's urls.py
6. Test with runserver

### Debugging Template Issues
- Templates are in project-level `templates/` directory (not in apps)
- Template context includes: user (from auth), messages (from Django messages framework)
- Media files accessed via `{{ MEDIA_URL }}` in templates

### Working with Vditor
- Vditor is initialized in teacher episode edit template
- Image uploads go through `/api/upload/` endpoint
- Content saved as markdown in `Episode.info_page_content`
- Students see rendered HTML via marked.js

## Important Notes

- This is an MVP project - some features are simplified (e.g., email verification prints to console)
- Use `uv` commands, not `pip` or `poetry`
- CSRF tokens required for all POST requests
- File uploads need MIME validation (handled by `python-magic`)
- Drag-and-drop reordering implemented for sections/episodes (recent feature)

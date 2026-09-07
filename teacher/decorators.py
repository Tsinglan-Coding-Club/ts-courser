"""
Teacher authorization decorators.

Three-layer permission system:
  1. teacher_required        — user must be verified teacher or admin
  2. require_course_permission — user must have scoped course access
  3. require_episode_ownership — episode's parent course must allow editing
"""

from django.shortcuts import redirect, get_object_or_404
from django.core.exceptions import PermissionDenied
from courses.models import Course, CourseTeacherMembership, Section, Episode


def teacher_required(view_func):
    """
    Decorator: only verified teachers and admins can access.

    Must be placed BELOW @login_required in the decorator stack
    (or used standalone since it also checks authentication).
    """
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        if not request.user.is_teacher and not request.user.is_admin:
            raise PermissionDenied("Only verified teachers can access this page.")
        return view_func(request, *args, **kwargs)
    return wrapper


def require_course_permission(required_role):
    """
    Decorator factory: ensure the teacher has the requested access to the course
    identified by URL kwarg ``course_id``.

    Admin users automatically bypass this check.
    Injects request.course (already fetched) to avoid duplicate DB queries.

    Must be placed BELOW @teacher_required so request.user is guaranteed.
    """
    def decorator(view_func):
        def wrapper(request, *args, **kwargs):
            course_id = kwargs.get('course_id')
            if course_id is None:
                raise ValueError("require_course_permission requires a 'course_id' URL kwarg.")

            course = get_object_or_404(Course, id=course_id)

            if not course.teacher_can(request.user, required_role):
                raise PermissionDenied("You do not have access to this course.")

            request.course = course
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def require_course_ownership(view_func):
    """Backward-compatible creator/manager check for course-level changes."""
    return require_course_permission(CourseTeacherMembership.MANAGE)(view_func)


def require_episode_ownership(view_func):
    """
    Decorator: ensure the teacher owns the episode's parent course.

    Admin users automatically bypass this check.
    Injects request.episode and request.course (already fetched).

    Must be placed BELOW @teacher_required.
    """
    def wrapper(request, *args, **kwargs):
        episode_id = kwargs.get('episode_id')
        if episode_id is None:
            raise ValueError("require_episode_ownership requires an 'episode_id' URL kwarg.")

        # select_related to avoid N+1 queries for section→course chain
        episode = get_object_or_404(
            Episode.objects.select_related('section__course'),
            id=episode_id
        )
        course = episode.section.course

        if not course.teacher_can(request.user, CourseTeacherMembership.EDIT):
            raise PermissionDenied("You can only edit course content you are assigned to.")

        request.episode = episode
        request.course = course
        return view_func(request, *args, **kwargs)
    return wrapper


def check_section_ownership(request, section_id):
    """
    Imperative check (not decorator): verify section belongs to user's course.

    Returns (section, course) tuple on success.
    Raises PermissionDenied if the user is not the course owner (and not admin).
    """
    section = get_object_or_404(
        Section.objects.select_related('course'),
        id=section_id
    )
    course = section.course

    if not course.teacher_can(request.user, CourseTeacherMembership.EDIT):
        raise PermissionDenied("You can only modify course content you are assigned to.")

    return section, course

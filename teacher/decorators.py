"""
Teacher authorization decorators.

Three-layer permission system:
  1. teacher_required        — user must be verified teacher or admin
  2. require_course_ownership — course must belong to user (admin bypass)
  3. require_episode_ownership — episode's parent course must belong to user (admin bypass)
"""

from django.shortcuts import redirect, get_object_or_404
from django.core.exceptions import PermissionDenied
from courses.models import Course, Section, Episode


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


def require_course_ownership(view_func):
    """
    Decorator: ensure the teacher owns the course identified by URL kwarg 'course_id'.

    Admin users automatically bypass this check.
    Injects request.course (already fetched) to avoid duplicate DB queries.

    Must be placed BELOW @teacher_required so request.user is guaranteed.
    """
    def wrapper(request, *args, **kwargs):
        course_id = kwargs.get('course_id')
        if course_id is None:
            raise ValueError("require_course_ownership requires a 'course_id' URL kwarg.")

        course = get_object_or_404(Course, id=course_id)

        if not request.user.is_admin and course.creator != request.user:
            raise PermissionDenied("You can only edit your own courses.")

        request.course = course
        return view_func(request, *args, **kwargs)
    return wrapper


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

        if not request.user.is_admin and course.creator != request.user:
            raise PermissionDenied("You can only edit your own content.")

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

    if not request.user.is_admin and course.creator != request.user:
        raise PermissionDenied("You can only modify your own course content.")

    return section, course

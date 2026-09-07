import mimetypes
from pathlib import PurePosixPath

from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404, HttpResponseForbidden

from courses.models import Course, Episode
from progress.models import CourseEnrollment


def _valid_media_path(path):
    parsed = PurePosixPath(path)
    return not parsed.is_absolute() and '..' not in parsed.parts and str(parsed) == path


def _can_access_course(user, course):
    if user.is_admin or course.creator_id == user.id:
        return True
    if not course.is_published:
        return False
    if user.is_teacher:
        return True
    return CourseEnrollment.objects.filter(user=user, course=course).exists()


@login_required
def protected_media(request, path):
    """Serve uploaded media through Django so account/course gates apply."""
    if not _valid_media_path(path) or not default_storage.exists(path):
        raise Http404

    if path.startswith(('episode_pdfs/', 'answer_pdfs/')):
        field_name = 'content_pdf' if path.startswith('episode_pdfs/') else 'answer_pdf'
        episode = Episode.objects.select_related('section__course').filter(
            **{field_name: path},
        ).first()
        if not episode:
            raise Http404
        if not _can_access_course(request.user, episode.section.course):
            return HttpResponseForbidden('You do not have access to this course.')
    elif path.startswith('course_thumbnails/'):
        course = Course.objects.filter(thumbnail=path).first()
        if not course:
            raise Http404
        if not (
            course.is_published
            or request.user.is_admin
            or course.creator_id == request.user.id
        ):
            return HttpResponseForbidden('You do not have access to this course.')
    elif not path.startswith(('avatars/', 'vditor_uploads/')):
        raise Http404

    content_type, _encoding = mimetypes.guess_type(path)
    response = FileResponse(
        default_storage.open(path, 'rb'),
        content_type=content_type or 'application/octet-stream',
    )
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response

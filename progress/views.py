from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.core.files.storage import default_storage
from django.conf import settings
from django.utils import timezone
from .models import (
    UserProgress, EpisodeReadStatus, CourseEnrollment, QuizSubmission,
    CodeSubmission, CodeSubmissionHistory,
)
from courses.models import CourseTeacherMembership, Episode, Course
from ts_courser.utils import ImageUploadValidationError, validate_and_reencode_image
from courses.quiz import validate_answers
from progress.validation import validate_test_results
from django.db import transaction
import json
import uuid
import os
import secrets


def _get_accessible_episode(request, episode_id, episode_type=None):
    """Return an episode only when it is accessible under the current course policy."""
    try:
        query = Episode.objects.select_related('section__course')
        if episode_type:
            query = query.filter(type=episode_type)
        episode = query.get(id=episode_id)
    except (ValueError, TypeError):
        return None, JsonResponse({'success': False, 'error': 'Invalid episode ID'}, status=400)
    except Episode.DoesNotExist:
        label = 'Episode' if not episode_type else f'{episode_type.title()} episode'
        return None, JsonResponse({'success': False, 'error': f'{label} not found'}, status=404)

    course = episode.section.course
    is_enrolled = CourseEnrollment.objects.filter(
        user=request.user, course=course
    ).exists()
    is_privileged = course.teacher_can(request.user, CourseTeacherMembership.VIEW)

    if not course.is_published or (not is_enrolled and not is_privileged):
        return None, JsonResponse(
            {'success': False, 'error': 'You do not have access to this course'},
            status=403,
        )

    return episode, None


@login_required
@require_POST
def update_progress(request):
    """AJAX endpoint to update user's current episode progress."""
    episode_id = request.POST.get('episode_id')

    if not episode_id:
        return JsonResponse({'success': False, 'error': 'Episode ID required'})

    episode, error_response = _get_accessible_episode(request, episode_id)
    if error_response:
        return error_response

    progress, created = UserProgress.objects.get_or_create(
        user=request.user,
        course=episode.section.course
    )
    progress.current_episode = episode
    progress.save()

    return JsonResponse({'success': True})


@login_required
@require_POST
def mark_episode(request):
    """AJAX endpoint to mark episode as read/unread."""
    episode_id = request.POST.get('episode_id')
    is_read = request.POST.get('is_read', 'true') == 'true'

    if not episode_id:
        return JsonResponse({'success': False, 'error': 'Episode ID required'})

    episode, error_response = _get_accessible_episode(request, episode_id)
    if error_response:
        return error_response

    read_status, created = EpisodeReadStatus.objects.get_or_create(
        user=request.user,
        episode=episode
    )
    read_status.is_read = is_read
    read_status.save()

    return JsonResponse({'success': True, 'is_read': is_read})


@login_required
@require_POST
def vditor_upload(request):
    """
    Handle file uploads from Vditor markdown editor.

    NOTE: This endpoint uses {'code': 0, 'data': {...}} response format
    instead of the project-standard {'success': True} because Vditor
    requires this specific JSON schema for its upload handler.
    """
    if 'file[]' not in request.FILES:
        return JsonResponse({'code': 1, 'msg': 'No file provided'})

    uploaded_files = request.FILES.getlist('file[]')
    success_files = []

    for uploaded_file in uploaded_files:
        try:
            uploaded_file = validate_and_reencode_image(
                uploaded_file, max_size_bytes=10 * 1024 * 1024
            )
        except ImageUploadValidationError:
            continue

        # Generate unique filename
        ext = os.path.splitext(uploaded_file.name)[1]
        unique_filename = f"{uuid.uuid4()}{ext}"
        file_path = os.path.join('vditor_uploads', unique_filename)

        # Save file
        saved_path = default_storage.save(file_path, uploaded_file)
        file_url = request.build_absolute_uri(settings.MEDIA_URL + saved_path)

        success_files.append(file_url)

    if success_files:
        return JsonResponse({
            'code': 0,
            'data': {
                'succMap': {f: f for f in success_files}
            }
        })
    else:
        return JsonResponse({'code': 1, 'msg': 'File upload failed'})


@login_required
@require_POST
def enroll_course(request):
    """AJAX endpoint to enroll in a course."""
    course_id = request.POST.get('course_id')

    if not course_id:
        return JsonResponse({'success': False, 'error': 'Course ID required'})

    try:
        course = Course.objects.get(id=course_id, is_published=True)

        # Check enrollment is open
        if not course.enrollment_open:
            return JsonResponse({
                'success': False,
                'error': 'Enrollment is currently closed for this course.'
            })

        # Check enrollment mode
        if course.enrollment_mode == 'code':
            entered_code = request.POST.get('course_code', '').strip().upper()
            if not entered_code:
                return JsonResponse({
                    'success': False,
                    'error': 'A course code is required to join this course.'
                })
            if not secrets.compare_digest(entered_code, (course.course_code or '').upper()):
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid course code. Please try again.'
                })

        # Check if already enrolled
        enrollment, created = CourseEnrollment.objects.get_or_create(
            user=request.user,
            course=course
        )

        if created:
            return JsonResponse({
                'success': True,
                'message': 'Successfully enrolled in the course!',
                'enrolled': True
            })
        else:
            return JsonResponse({
                'success': True,
                'message': 'You are already enrolled in this course.',
                'enrolled': True
            })

    except Course.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Course not found'})


@login_required
@require_POST
def unenroll_course(request):
    """AJAX endpoint to unenroll from a course."""
    course_id = request.POST.get('course_id')

    if not course_id:
        return JsonResponse({'success': False, 'error': 'Course ID required'})

    try:
        course = Course.objects.get(id=course_id)
        enrollment = CourseEnrollment.objects.filter(
            user=request.user,
            course=course
        ).first()

        if enrollment:
            enrollment.delete()
            return JsonResponse({
                'success': True,
                'message': 'Successfully unenrolled from the course.',
                'enrolled': False
            })
        else:
            return JsonResponse({
                'success': True,
                'message': 'You are not enrolled in this course.',
                'enrolled': False
            })

    except Course.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Course not found'})


@login_required
@require_POST
def submit_quiz(request):
    """Submit quiz answers for an episode."""
    episode_id = request.POST.get('episode_id')
    answers_json = request.POST.get('answers', '{}')

    if not episode_id:
        return JsonResponse({'success': False, 'error': 'Episode ID required'})

    episode, error_response = _get_accessible_episode(request, episode_id, 'quiz')
    if error_response:
        return error_response

    course = episode.section.course

    try:
        answers = validate_answers(episode, json.loads(answers_json))
    except (json.JSONDecodeError, ValueError) as error:
        return JsonResponse({'success': False, 'error': str(error)}, status=400)
    has_frq = any(q['type'] == 'frq' for q in answers['questions'])
    policy = episode.quiz_release_policy
    automatic = policy == 'immediate' or (
        policy == 'inherit' and course.auto_release_results and not has_frq
    )
    answers_json = json.dumps(answers)
    with transaction.atomic():
        submission, created = QuizSubmission.objects.select_for_update().get_or_create(
            user=request.user, episode=episode
        )
        try:
            previous_answers = json.loads(submission.answers)
        except (json.JSONDecodeError, TypeError):
            previous_answers = None
        changed = created or previous_answers != answers
        if changed:
            # A grade belongs to the previous answers, never to a replacement.
            submission.frq_grades = '{}'
            submission.question_comments = {}
            submission.released_at = timezone.now() if automatic else None
            submission.submitted_at = timezone.now()
        submission.answers = answers_json
        submission.save()
        released_at = submission.released_at

    # Mark episode as read on submission
    EpisodeReadStatus.objects.update_or_create(
        user=request.user,
        episode=episode,
        defaults={'is_read': True}
    )

    return JsonResponse({
        'success': True,
        'message': 'Quiz submitted successfully!',
        'auto_released': released_at is not None,
    })


@login_required
@require_POST
def upload_code(request):
    """Upload code to the server without making it visible as a submission."""
    episode_id = request.POST.get('episode_id')
    code = request.POST.get('code', '')

    if not episode_id:
        return JsonResponse({'success': False, 'error': 'Episode ID required'})

    episode, error_response = _get_accessible_episode(request, episode_id, 'code')
    if error_response:
        return error_response

    CodeSubmission.objects.update_or_create(
        user=request.user,
        episode=episode,
        defaults={
            'code': code,
            'test_results': '[]',
            'is_submitted': False,
            'submitted_at': None,
        },
    )

    return JsonResponse({'success': True, 'message': 'Code uploaded successfully.'})


@login_required
@require_POST
def submit_code(request):
    """Record a formally submitted code upload and its browser-side test results."""
    episode_id = request.POST.get('episode_id')
    code = request.POST.get('code', '')
    test_results_json = request.POST.get('test_results', '[]')

    if not episode_id:
        return JsonResponse({'success': False, 'error': 'Episode ID required'})

    episode, error_response = _get_accessible_episode(request, episode_id, 'code')
    if error_response:
        return error_response

    # Validate test_results JSON
    try:
        test_results = validate_test_results(json.loads(test_results_json))
    except (json.JSONDecodeError, ValueError) as error:
        return JsonResponse({'success': False, 'error': str(error)}, status=400)
    test_results_json = json.dumps(test_results)

    # Keep the mutable upload for editor recovery, and separately preserve an
    # immutable snapshot for each formal submission.
    with transaction.atomic():
        CodeSubmission.objects.update_or_create(
            user=request.user,
            episode=episode,
            defaults={
                'code': code,
                'test_results': test_results_json,
                'is_submitted': True,
                'submitted_at': timezone.now(),
            },
        )
        history = CodeSubmissionHistory.objects.create(
            user=request.user,
            episode=episode,
            code=code,
            test_results=test_results_json,
        )

    # Mark episode as read on submission
    EpisodeReadStatus.objects.update_or_create(
        user=request.user,
        episode=episode,
        defaults={'is_read': True}
    )

    return JsonResponse({
        'success': True,
        'message': 'Code submitted successfully!',
        'history_id': history.id,
    })


@login_required
def code_history(request):
    """Return the current student's formal submission history for an episode."""
    episode_id = request.GET.get('episode_id')
    if not episode_id:
        return JsonResponse({'success': False, 'error': 'Episode ID required'}, status=400)

    episode, error_response = _get_accessible_episode(request, episode_id, 'code')
    if error_response:
        return error_response

    history = CodeSubmissionHistory.objects.filter(
        user=request.user, episode=episode
    ).values('id', 'submitted_at', 'code').order_by('-submitted_at', '-id')
    return JsonResponse({
        'success': True,
        'history': [
            {
                'id': item['id'],
                'submitted_at': item['submitted_at'].isoformat(),
                'code': item['code'],
            }
            for item in history
        ],
    })


@login_required
@require_POST
def restore_code_history(request, history_id):
    """Return a student's historical snapshot so the browser can restore a draft."""
    snapshot = get_object_or_404(
        CodeSubmissionHistory.objects.select_related('episode__section__course'),
        id=history_id,
        user=request.user,
    )
    episode, error_response = _get_accessible_episode(
        request, snapshot.episode_id, 'code'
    )
    if error_response:
        return error_response
    if episode.id != snapshot.episode_id:
        return JsonResponse({'success': False, 'error': 'Code submission not found'}, status=404)

    # This intentionally does not update CodeSubmission or create a snapshot.
    return JsonResponse({
        'success': True,
        'id': snapshot.id,
        'code': snapshot.code,
        'submitted_at': snapshot.submitted_at.isoformat(),
    })


@login_required
def my_courses(request):
    """View all courses the user has enrolled in."""
    # Get all enrolled courses
    enrollments = CourseEnrollment.objects.filter(user=request.user).select_related('course')

    # Build course data with progress
    courses_data = []
    for enrollment in enrollments:
        course = enrollment.course

        # Get all episodes in the course
        total_episodes = 0
        read_episodes = 0

        for section in course.sections.all():
            episodes = section.episodes.all()
            total_episodes += episodes.count()

            # Count read episodes
            for episode in episodes:
                if EpisodeReadStatus.objects.filter(
                    user=request.user,
                    episode=episode,
                    is_read=True
                ).exists():
                    read_episodes += 1

        # Calculate progress percentage
        progress_percentage = 0
        if total_episodes > 0:
            progress_percentage = int((read_episodes / total_episodes) * 100)

        # Get current episode (last viewed)
        user_progress = UserProgress.objects.filter(
            user=request.user,
            course=course
        ).first()

        current_episode = user_progress.current_episode if user_progress else None

        courses_data.append({
            'course': course,
            'enrollment': enrollment,
            'total_episodes': total_episodes,
            'read_episodes': read_episodes,
            'progress_percentage': progress_percentage,
            'current_episode': current_episode,
        })

    context = {
        'courses_data': courses_data,
    }

    return render(request, 'progress/my_courses.html', context)

from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.core.files.storage import default_storage
from django.conf import settings
from django.utils import timezone
from .models import UserProgress, EpisodeReadStatus, CourseEnrollment, QuizSubmission
from courses.models import Episode, Course
from ts_courser.utils import compress_image
import json
import uuid
import os
import magic
import secrets


@login_required
@require_POST
def update_progress(request):
    """AJAX endpoint to update user's current episode progress."""
    episode_id = request.POST.get('episode_id')

    if not episode_id:
        return JsonResponse({'success': False, 'error': 'Episode ID required'})

    try:
        episode = Episode.objects.get(id=episode_id)
        progress, created = UserProgress.objects.get_or_create(
            user=request.user,
            course=episode.section.course
        )
        progress.current_episode = episode
        progress.save()

        return JsonResponse({'success': True})
    except Episode.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Episode not found'})


@login_required
@require_POST
def mark_episode(request):
    """AJAX endpoint to mark episode as read/unread."""
    episode_id = request.POST.get('episode_id')
    is_read = request.POST.get('is_read', 'true') == 'true'

    if not episode_id:
        return JsonResponse({'success': False, 'error': 'Episode ID required'})

    try:
        episode = Episode.objects.get(id=episode_id)
        read_status, created = EpisodeReadStatus.objects.get_or_create(
            user=request.user,
            episode=episode
        )
        read_status.is_read = is_read
        read_status.save()

        return JsonResponse({'success': True, 'is_read': is_read})
    except Episode.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Episode not found'})


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
        # File validation
        if uploaded_file.size > 10 * 1024 * 1024:  # 10MB limit
            continue

        # MIME type validation
        try:
            mime = magic.Magic(mime=True)
            file_mime = mime.from_buffer(uploaded_file.read(1024))
            uploaded_file.seek(0)

            # Only allow images
            if not file_mime.startswith('image/'):
                continue
        except Exception:
            continue

        # Compress images larger than 1MB before saving
        uploaded_file = compress_image(uploaded_file)

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

    try:
        episode = Episode.objects.get(id=episode_id, type='quiz')
    except Episode.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Quiz episode not found'})

    course = episode.section.course

    # Check enrollment
    is_enrolled = CourseEnrollment.objects.filter(
        user=request.user, course=course
    ).exists()
    if not is_enrolled and not (request.user.is_teacher or request.user.is_admin):
        return JsonResponse({'success': False, 'error': 'You must be enrolled to submit'})

    # Parse and validate answers
    try:
        answers = json.loads(answers_json)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid answers format'})

    # Determine if there are FRQ questions
    has_frq = any(q.get('type') == 'frq' for q in answers.get('questions', []))

    # Get existing submission so we can preserve a manual teacher release
    existing = QuizSubmission.objects.filter(
        user=request.user, episode=episode
    ).first()

    # Auto-release: episode-level quiz_show_results (immediate, even with FRQ)
    # or course-level auto_release_results (only for non-FRQ)
    if episode.quiz_show_results:
        released_at = timezone.now()
    elif course.auto_release_results and not has_frq:
        released_at = timezone.now()
    else:
        released_at = None

    # Preserve existing manual release if the new logic wouldn't auto-release
    if not released_at and existing and existing.released_at:
        released_at = existing.released_at

    submission, created = QuizSubmission.objects.update_or_create(
        user=request.user,
        episode=episode,
        defaults={
            'answers': answers_json,
            'released_at': released_at,
        }
    )

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

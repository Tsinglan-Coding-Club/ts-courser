
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Prefetch
from .models import Course, Tag, Section, Episode
from progress.models import UserProgress, EpisodeReadStatus, CourseEnrollment


@login_required
def course_list(request):
    """Display all published courses with optional tag filtering."""
    courses = Course.objects.filter(is_published=True).prefetch_related('tags')

    # Tag filtering
    track_filter = request.GET.get('track')
    subject_filter = request.GET.get('subject')

    if track_filter:
        courses = courses.filter(tags__name=track_filter, tags__category='track')
    if subject_filter:
        courses = courses.filter(tags__name=subject_filter, tags__category='subject')

    # Get IDs of courses the user is enrolled in
    enrolled_course_ids = set(
        CourseEnrollment.objects.filter(user=request.user).values_list('course_id', flat=True)
    )

    # Get all tags for filter options
    track_tags = Tag.objects.filter(category='track')
    subject_tags = Tag.objects.filter(category='subject')

    context = {
        'courses': courses.distinct(),
        'enrolled_course_ids': enrolled_course_ids,
        'track_tags': track_tags,
        'subject_tags': subject_tags,
        'selected_track': track_filter,
        'selected_subject': subject_filter,
    }
    return render(request, 'courses/course_list.html', context)


@login_required
def course_overview(request, course_id):
    """Display course preview and enrollment (landing page)."""
    course = get_object_or_404(Course, id=course_id, is_published=True)

    is_enrolled = CourseEnrollment.objects.filter(
        user=request.user,
        course=course
    ).exists()
    is_teacher_or_admin = request.user.is_teacher or request.user.is_admin

    # Enrolled students should use the dashboard, not the overview
    if is_enrolled:
        return redirect('courses:course_dashboard', course_id=course.id)

    # Get sections with episodes for content listing
    sections = Section.objects.filter(course=course).prefetch_related(
        Prefetch(
            'episodes',
            queryset=Episode.objects.all().order_by('order')
        )
    )

    context = {
        'course': course,
        'sections': sections,
        'is_enrolled': is_enrolled,
        'is_teacher_or_admin': is_teacher_or_admin,
    }
    return render(request, 'courses/course_overview.html', context)


@login_required
def course_dashboard(request, course_id):
    """Enrolled student hub: progress, course content, continue learning."""
    course = get_object_or_404(Course, id=course_id, is_published=True)

    is_enrolled = CourseEnrollment.objects.filter(
        user=request.user, course=course
    ).exists()
    is_teacher_or_admin = request.user.is_teacher or request.user.is_admin

    # Guard: must be enrolled (or teacher/admin) to access dashboard
    if not is_enrolled and not is_teacher_or_admin:
        messages.warning(request, 'You must enroll in this course to access the dashboard.')
        return redirect('courses:course_overview', course_id=course.id)

    # Get or create user progress
    progress, created = UserProgress.objects.get_or_create(
        user=request.user,
        course=course
    )

    # Get all sections with episodes for content listing
    sections = Section.objects.filter(course=course).prefetch_related(
        Prefetch(
            'episodes',
            queryset=Episode.objects.all().order_by('order')
        )
    )

    # Progress calculation
    all_episodes = Episode.objects.filter(section__course=course)
    read_episodes = EpisodeReadStatus.objects.filter(
        user=request.user,
        episode__section__course=course,
        is_read=True
    ).count()
    total_episodes = all_episodes.count()
    progress_percentage = (read_episodes / total_episodes * 100) if total_episodes > 0 else 0

    context = {
        'course': course,
        'sections': sections,
        'progress': progress,
        'total_episodes': total_episodes,
        'read_episodes': read_episodes,
        'progress_percentage': round(progress_percentage, 1),
    }
    return render(request, 'courses/course_dashboard.html', context)


@login_required
def learning_interface(request, course_id, episode_id=None):
    """Main learning interface with sidebar navigation."""
    course = get_object_or_404(Course, id=course_id, is_published=True)

    # Auto-enroll for open-mode courses (must happen before enrollment guard)
    is_enrolled = CourseEnrollment.objects.filter(
        user=request.user, course=course
    ).exists()
    is_teacher_or_admin = request.user.is_teacher or request.user.is_admin

    if not is_enrolled and course.enrollment_mode == 'open':
        CourseEnrollment.objects.get_or_create(user=request.user, course=course)
        is_enrolled = True

    # Enrollment guard: must be enrolled to access learning interface
    if not is_enrolled and not is_teacher_or_admin:
        messages.warning(request, 'You must enroll in this course to access the learning materials.')
        return redirect('courses:course_overview', course_id=course.id)

    # Get or create user progress
    progress, created = UserProgress.objects.get_or_create(
        user=request.user,
        course=course
    )

    # Get all sections with episodes
    sections = Section.objects.filter(course=course).prefetch_related(
        Prefetch(
            'episodes',
            queryset=Episode.objects.all().order_by('order')
        )
    )

    # Determine current episode
    if episode_id:
        current_episode = get_object_or_404(Episode, id=episode_id, section__course=course)
    elif progress.current_episode:
        current_episode = progress.current_episode
    else:
        # Get first episode
        first_section = sections.first()
        current_episode = first_section.episodes.first() if first_section else None

    # Update progress to current episode
    if current_episode and progress.current_episode != current_episode:
        progress.current_episode = current_episode
        progress.save()

    # Get read statuses for all episodes
    read_statuses = EpisodeReadStatus.objects.filter(
        user=request.user,
        episode__section__course=course
    ).values_list('episode_id', 'is_read')
    read_status_dict = dict(read_statuses)

    # Get current episode read status
    current_read_status = None
    quiz_submission = None
    quiz_answers_json = None
    if current_episode:
        current_read_status, _ = EpisodeReadStatus.objects.get_or_create(
            user=request.user,
            episode=current_episode
        )
        if current_episode.type == 'quiz':
            from progress.models import QuizSubmission
            import json as _json
            quiz_submission = QuizSubmission.objects.filter(
                user=request.user, episode=current_episode
            ).first()
            quiz_answers_json = None
            if quiz_submission and quiz_submission.released_at and quiz_submission.answers:
                quiz_answers_json = quiz_submission.answers

    context = {
        'course': course,
        'sections': sections,
        'current_episode': current_episode,
        'current_read_status': current_read_status,
        'read_status_dict': read_status_dict,
        'is_teacher': request.user.is_teacher,
        'quiz_submission': quiz_submission,
        'quiz_answers_json': quiz_answers_json,
        'quiz_require_all': getattr(current_episode, 'quiz_require_all', True) if current_episode else True,
        'quiz_show_results': getattr(current_episode, 'quiz_show_results', False) if current_episode else False,
    }
    return render(request, 'courses/learning_interface.html', context)

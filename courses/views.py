from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
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

    # Get all tags for filter options
    track_tags = Tag.objects.filter(category='track')
    subject_tags = Tag.objects.filter(category='subject')

    context = {
        'courses': courses.distinct(),
        'track_tags': track_tags,
        'subject_tags': subject_tags,
        'selected_track': track_filter,
        'selected_subject': subject_filter,
    }
    return render(request, 'courses/course_list.html', context)


@login_required
def course_overview(request, course_id):
    """Display course overview with user progress."""
    course = get_object_or_404(Course, id=course_id, is_published=True)

    # Get or create user progress
    progress, created = UserProgress.objects.get_or_create(
        user=request.user,
        course=course
    )

    # Get all episodes for progress calculation
    all_episodes = Episode.objects.filter(section__course=course)
    read_episodes = EpisodeReadStatus.objects.filter(
        user=request.user,
        episode__section__course=course,
        is_read=True
    ).count()

    total_episodes = all_episodes.count()
    progress_percentage = (read_episodes / total_episodes * 100) if total_episodes > 0 else 0

    # Check if user is enrolled in this course
    is_enrolled = CourseEnrollment.objects.filter(
        user=request.user,
        course=course
    ).exists()

    context = {
        'course': course,
        'progress': progress,
        'total_episodes': total_episodes,
        'read_episodes': read_episodes,
        'progress_percentage': round(progress_percentage, 1),
        'is_enrolled': is_enrolled,
    }
    return render(request, 'courses/course_overview.html', context)


@login_required
def learning_interface(request, course_id, episode_id=None):
    """Main learning interface with sidebar navigation."""
    course = get_object_or_404(Course, id=course_id, is_published=True)

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
    if current_episode:
        current_read_status, _ = EpisodeReadStatus.objects.get_or_create(
            user=request.user,
            episode=current_episode
        )

    context = {
        'course': course,
        'sections': sections,
        'current_episode': current_episode,
        'current_read_status': current_read_status,
        'read_status_dict': read_status_dict,
        'is_teacher': request.user.is_teacher,
    }
    return render(request, 'courses/learning_interface.html', context)

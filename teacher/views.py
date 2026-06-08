from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.db import models
from courses.models import Course, Section, Episode, Tag
from .decorators import (
    teacher_required,
    require_course_ownership,
    require_episode_ownership,
    check_section_ownership,
)
import magic
import os

from ts_courser.utils import compress_image


@teacher_required
def course_list(request):
    """List courses for teacher management. Teachers see only their own; admins see all."""
    if request.user.is_admin:
        courses = Course.objects.all().prefetch_related('tags', 'creator')
    else:
        courses = Course.objects.filter(creator=request.user).prefetch_related('tags', 'creator')
    return render(request, 'teacher/course_list.html', {'courses': courses})


@teacher_required
def course_create(request):
    """Create a new course."""
    if request.method == 'POST':
        title = request.POST.get('title')
        description = request.POST.get('description')
        is_published = request.POST.get('is_published') == 'on'
        tag_ids = request.POST.getlist('tags')

        if not all([title, description]):
            messages.error(request, 'Title and description are required.')
            return redirect('teacher:course_create')

        course = Course.objects.create(
            title=title,
            description=description,
            creator=request.user,
            is_published=is_published
        )

        # Handle thumbnail upload (compress if > 1MB)
        if 'thumbnail' in request.FILES:
            course.thumbnail = compress_image(request.FILES['thumbnail'])
            course.save()

        # Add tags
        if tag_ids:
            course.tags.set(tag_ids)

        messages.success(request, f'Course "{title}" created successfully!')
        return redirect('teacher:course_edit', course_id=course.id)

    tags = Tag.objects.all()
    return render(request, 'teacher/course_form.html', {'tags': tags})


@teacher_required
@require_course_ownership
def course_edit(request, course_id):
    """Edit an existing course. Only the creator (or admin) can edit."""
    course = request.course  # Injected by require_course_ownership

    if request.method == 'POST':
        course.title = request.POST.get('title', course.title)
        course.description = request.POST.get('description', course.description)
        course.is_published = request.POST.get('is_published') == 'on'
        tag_ids = request.POST.getlist('tags')

        # Handle thumbnail upload (compress if > 1MB)
        if 'thumbnail' in request.FILES:
            course.thumbnail = compress_image(request.FILES['thumbnail'])

        course.save()

        # Update tags
        if tag_ids:
            course.tags.set(tag_ids)
        else:
            course.tags.clear()

        messages.success(request, f'Course "{course.title}" updated successfully!')
        return redirect('teacher:course_edit', course_id=course.id)

    tags = Tag.objects.all()
    sections = Section.objects.filter(course=course).prefetch_related('episodes')

    # Calculate total episodes
    total_episodes = sum(section.episodes.count() for section in sections)

    context = {
        'course': course,
        'tags': tags,
        'sections': sections,
        'total_episodes': total_episodes,
    }
    return render(request, 'teacher/course_edit.html', context)


@teacher_required
def section_create(request):
    """Create a new section. Only the course owner (or admin) can add sections."""
    if request.method == 'POST':
        course_id = request.POST.get('course_id')
        title = request.POST.get('title')

        if not all([course_id, title]):
            messages.error(request, 'Course and title are required.')
            return redirect('teacher:course_list')

        course = get_object_or_404(Course, id=course_id)

        # Ownership check: only the course creator or admin can add sections
        if not request.user.is_admin and course.creator != request.user:
            raise PermissionDenied("You can only add sections to your own courses.")

        # Auto-calculate order (max + 1)
        max_order = Section.objects.filter(course=course).aggregate(
            models.Max('order')
        )['order__max']
        new_order = (max_order or -1) + 1

        Section.objects.create(
            course=course,
            title=title,
            order=new_order
        )

        messages.success(request, f'Section "{title}" created successfully!')
        return redirect('teacher:course_edit', course_id=course_id)

    return redirect('teacher:course_list')


@teacher_required
def episode_create(request):
    """Create a new episode. Only the parent course owner (or admin) can add episodes."""
    if request.method == 'POST':
        section_id = request.POST.get('section_id')
        title = request.POST.get('title')
        episode_type = request.POST.get('type', 'material')

        if not all([section_id, title]):
            messages.error(request, 'Section and title are required.')
            return redirect('teacher:course_list')

        # Ownership check: trace back to parent course
        section, course = check_section_ownership(request, section_id)

        # Auto-calculate order (max + 1)
        max_order = Episode.objects.filter(section=section).aggregate(
            models.Max('order')
        )['order__max']
        new_order = (max_order or -1) + 1

        episode = Episode.objects.create(
            section=section,
            title=title,
            type=episode_type,
            order=new_order
        )

        messages.success(request, f'Episode "{title}" created successfully!')
        return redirect('teacher:episode_edit', episode_id=episode.id)

    return redirect('teacher:course_list')


@teacher_required
@require_episode_ownership
def episode_edit(request, episode_id):
    """Edit an episode with markdown editor and file uploads."""
    episode = request.episode  # Injected by require_episode_ownership
    course = request.course

    if request.method == 'POST':
        episode.title = request.POST.get('title', episode.title)
        episode.type = request.POST.get('type', episode.type)
        episode.order = request.POST.get('order', episode.order)
        episode.info_page_content = request.POST.get('info_page_content', '')

        if episode.order:
            episode.order = int(episode.order)
        else:
            messages.error(request, 'Episode not found.')

        # Handle PDF uploads with validation
        if 'content_pdf' in request.FILES:
            pdf_file = request.FILES['content_pdf']
            if validate_pdf(pdf_file):
                episode.content_pdf = pdf_file
            else:
                messages.error(request, 'Invalid PDF file for content.')

        if 'answer_pdf' in request.FILES and episode.type == 'quiz':
            pdf_file = request.FILES['answer_pdf']
            if validate_pdf(pdf_file):
                episode.answer_pdf = pdf_file
            else:
                messages.error(request, 'Invalid PDF file for answers.')

        # Code episode layout toggles
        episode.show_interactive = request.POST.get('show_interactive') == 'on'
        episode.show_reference = request.POST.get('show_reference') == 'on'

        episode.save()
        messages.success(request, f'Episode "{episode.title}" updated successfully!')
        return redirect('teacher:course_edit', course_id=course.id)

    context = {
        'episode': episode,
        'course': course,
        'type_options': Episode.TYPE_CHOICES,
    }
    return render(request, 'teacher/episode_edit.html', context)


@teacher_required
def tag_create(request):
    """Create a new tag via AJAX."""
    if request.method == 'POST':
        name = request.POST.get('name')
        category = request.POST.get('category', 'subject')

        if not name:
            return JsonResponse({'success': False, 'error': 'Name is required'})

        try:
            tag = Tag.objects.create(name=name, category=category)
            return JsonResponse({
                'success': True,
                'tag': {
                    'id': tag.id,
                    'name': tag.name,
                    'category': tag.category
                }
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Invalid request'})


@teacher_required
def section_reorder(request):
    """Reorder sections via AJAX. Only the course owner (or admin) can reorder."""
    if request.method == 'POST':
        try:
            import json
            data = json.loads(request.body)
            section_orders = data.get('section_orders', [])

            if not section_orders:
                return JsonResponse({'success': False, 'error': 'No sections provided'})

            # Verify ownership: all sections must belong to the same course owned by user
            section_ids = [item.get('id') for item in section_orders]
            sections = Section.objects.filter(id__in=section_ids).select_related('course')

            if len(sections) != len(section_ids):
                return JsonResponse({'success': False, 'error': 'Some sections not found'})

            # All sections must belong to the same course
            course_ids = set(s.course_id for s in sections)
            if len(course_ids) != 1:
                return JsonResponse({'success': False, 'error': 'Sections must belong to the same course'})

            course = sections[0].course
            if not request.user.is_admin and course.creator != request.user:
                return JsonResponse({'success': False, 'error': 'Permission denied'})

            for section in sections:
                new_order = next(
                    (item['order'] for item in section_orders if item['id'] == section.id),
                    section.order
                )
                section.order = new_order
                section.save()

            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Invalid request'})


@teacher_required
def episode_reorder(request):
    """Reorder episodes via AJAX. Only the parent course owner (or admin) can reorder."""
    if request.method == 'POST':
        try:
            import json
            data = json.loads(request.body)
            episode_orders = data.get('episode_orders', [])

            if not episode_orders:
                return JsonResponse({'success': False, 'error': 'No episodes provided'})

            # Verify ownership: all episodes must belong to the same course owned by user
            episode_ids = [item.get('id') for item in episode_orders]
            episodes = Episode.objects.filter(id__in=episode_ids).select_related(
                'section__course'
            )

            if len(episodes) != len(episode_ids):
                return JsonResponse({'success': False, 'error': 'Some episodes not found'})

            # All episodes must belong to the same course
            course_ids = set(e.section.course_id for e in episodes)
            if len(course_ids) != 1:
                return JsonResponse({'success': False, 'error': 'Episodes must belong to the same course'})

            course = episodes[0].section.course
            if not request.user.is_admin and course.creator != request.user:
                return JsonResponse({'success': False, 'error': 'Permission denied'})

            for episode in episodes:
                new_order = next(
                    (item['order'] for item in episode_orders if item['id'] == episode.id),
                    episode.order
                )
                episode.order = new_order
                episode.save()

            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Invalid request'})


# ========== Delete Views ==========

@teacher_required
def course_delete(request, course_id):
    """Delete a course. Only the creator (or admin) can delete."""
    course = get_object_or_404(Course, id=course_id)

    if not request.user.is_admin and course.creator != request.user:
        raise PermissionDenied("You can only delete your own courses.")

    if request.method == 'POST':
        course_title = course.title
        course.delete()
        messages.success(request, f'Course "{course_title}" deleted successfully!')
        return redirect('teacher:course_list')

    return redirect('teacher:course_edit', course_id=course_id)


@teacher_required
def section_delete(request, section_id):
    """Delete a section. Only the parent course owner (or admin) can delete."""
    section, course = check_section_ownership(request, section_id)

    if request.method == 'POST':
        section_title = section.title
        section.delete()
        messages.success(request, f'Section "{section_title}" deleted successfully!')
        return redirect('teacher:course_edit', course_id=course.id)

    return redirect('teacher:course_edit', course_id=course.id)


@teacher_required
def episode_delete(request, episode_id):
    """Delete an episode. Only the parent course owner (or admin) can delete."""
    episode = get_object_or_404(
        Episode.objects.select_related('section__course'),
        id=episode_id
    )
    course = episode.section.course

    if not request.user.is_admin and course.creator != request.user:
        raise PermissionDenied("You can only delete your own content.")

    if request.method == 'POST':
        episode_title = episode.title
        section = episode.section
        episode.delete()
        messages.success(request, f'Episode "{episode_title}" deleted successfully!')
        return redirect('teacher:course_edit', course_id=course.id)

    return redirect('teacher:course_edit', course_id=course.id)


def validate_pdf(pdf_file):
    """Validate uploaded PDF file."""
    # Size check (15MB limit)
    if pdf_file.size > 15 * 1024 * 1024:
        return False

    # MIME type check
    try:
        mime = magic.Magic(mime=True)
        file_mime = mime.from_buffer(pdf_file.read(2048))
        pdf_file.seek(0)

        if file_mime not in ['application/pdf', 'application/x-pdf']:
            return False
    except Exception:
        return False

    # File header check (PDF magic number)
    header = pdf_file.read(4)
    pdf_file.seek(0)

    if header != b'%PDF':
        return False

    return True

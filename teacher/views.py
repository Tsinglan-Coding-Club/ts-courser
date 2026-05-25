from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.db import models
from courses.models import Course, Section, Episode, Tag
import magic
import os


def teacher_required(view_func):
    """Decorator to check if user is a verified teacher."""
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        if not request.user.is_teacher and not request.user.is_admin:
            raise PermissionDenied("Only verified teachers can access this page.")
        return view_func(request, *args, **kwargs)
    return wrapper


@teacher_required
def course_list(request):
    """List all courses for teacher management."""
    courses = Course.objects.all().prefetch_related('tags', 'creator')
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

        # Handle thumbnail upload
        if 'thumbnail' in request.FILES:
            course.thumbnail = request.FILES['thumbnail']
            course.save()

        # Add tags
        if tag_ids:
            course.tags.set(tag_ids)

        messages.success(request, f'Course "{title}" created successfully!')
        return redirect('teacher:course_edit', course_id=course.id)

    tags = Tag.objects.all()
    return render(request, 'teacher/course_form.html', {'tags': tags})


@teacher_required
def course_edit(request, course_id):
    """Edit an existing course."""
    course = get_object_or_404(Course, id=course_id)

    if request.method == 'POST':
        course.title = request.POST.get('title', course.title)
        course.description = request.POST.get('description', course.description)
        course.is_published = request.POST.get('is_published') == 'on'
        tag_ids = request.POST.getlist('tags')

        # Handle thumbnail upload
        if 'thumbnail' in request.FILES:
            course.thumbnail = request.FILES['thumbnail']

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
    """Create a new section."""
    if request.method == 'POST':
        course_id = request.POST.get('course_id')
        title = request.POST.get('title')

        if not all([course_id, title]):
            messages.error(request, 'Course and title are required.')
            return redirect('teacher:course_list')

        course = get_object_or_404(Course, id=course_id)

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
    """Create a new episode."""
    if request.method == 'POST':
        section_id = request.POST.get('section_id')
        title = request.POST.get('title')
        episode_type = request.POST.get('type', 'material')

        if not all([section_id, title]):
            messages.error(request, 'Section and title are required.')
            return redirect('teacher:course_list')

        section = get_object_or_404(Section, id=section_id)

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
def episode_edit(request, episode_id):
    """Edit an episode with markdown editor and file uploads."""
    episode = get_object_or_404(Episode, id=episode_id)

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

        episode.save()
        messages.success(request, f'Episode "{episode.title}" updated successfully!')
        return redirect('teacher:course_edit', course_id=episode.section.course.id)

    context = {
        'episode': episode,
        'course': episode.section.course,
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
    """Reorder sections via AJAX."""
    if request.method == 'POST':
        try:
            import json
            data = json.loads(request.body)
            section_orders = data.get('section_orders', [])

            for item in section_orders:
                section_id = item.get('id')
                new_order = item.get('order')
                section = Section.objects.get(id=section_id)
                section.order = new_order
                section.save()

            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Invalid request'})


@teacher_required
def episode_reorder(request):
    """Reorder episodes via AJAX."""
    if request.method == 'POST':
        try:
            import json
            data = json.loads(request.body)
            episode_orders = data.get('episode_orders', [])

            for item in episode_orders:
                episode_id = item.get('id')
                new_order = item.get('order')
                episode = Episode.objects.get(id=episode_id)
                episode.order = new_order
                episode.save()

            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Invalid request'})


def validate_pdf(pdf_file):
    """Validate uploaded PDF file."""
    # Size check (50MB limit)
    if pdf_file.size > 50 * 1024 * 1024:
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

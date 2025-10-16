from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.core.files.storage import default_storage
from django.conf import settings
from .models import UserProgress, EpisodeReadStatus
from courses.models import Episode
import uuid
import os
import magic


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
    """Handle file uploads from Vditor markdown editor."""
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

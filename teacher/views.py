from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db import models, transaction
from courses.models import Course, Section, Episode, Tag
from courses.quiz import _parse_quiz_markdown
from progress.models import CourseEnrollment, EpisodeReadStatus, QuizSubmission, CodeSubmission
from .decorators import (
    teacher_required,
    require_course_ownership,
    require_episode_ownership,
    check_section_ownership,
)
import json
import logging
import magic

from ts_courser.utils import ImageUploadValidationError, validate_and_reencode_image
from progress.validation import validate_test_results

logger = logging.getLogger(__name__)

COURSE_THUMBNAIL_ASPECT_RATIO = (16, 9)


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

        thumbnail = None
        if 'thumbnail' in request.FILES:
            try:
                thumbnail = validate_and_reencode_image(
                    request.FILES['thumbnail'],
                    max_size_bytes=10 * 1024 * 1024,
                    crop_aspect_ratio=COURSE_THUMBNAIL_ASPECT_RATIO,
                )
            except ImageUploadValidationError as error:
                messages.error(request, str(error))
                return redirect('teacher:course_create')

        course = Course.objects.create(
            title=title,
            description=description,
            creator=request.user,
            is_published=is_published
        )

        # Save the validated and centre-cropped thumbnail.
        if thumbnail:
            course.thumbnail = thumbnail
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
        new_mode = request.POST.get('enrollment_mode')
        if new_mode in ('open', 'code'):
            course.enrollment_mode = new_mode
        course.enrollment_open = request.POST.get('enrollment_open') == 'on'
        course.auto_release_results = request.POST.get('auto_release_results') == 'on'
        tag_ids = request.POST.getlist('tags')

        # Regenerate course code if requested (only in code mode)
        if request.POST.get('regenerate_code') == '1' and course.enrollment_mode == 'code':
            course.course_code = course._generate_code()

        # Validate and centre-crop a replacement thumbnail.
        if 'thumbnail' in request.FILES:
            try:
                course.thumbnail = validate_and_reencode_image(
                    request.FILES['thumbnail'],
                    max_size_bytes=10 * 1024 * 1024,
                    crop_aspect_ratio=COURSE_THUMBNAIL_ASPECT_RATIO,
                )
            except ImageUploadValidationError as error:
                messages.error(request, str(error))
                return redirect('teacher:course_edit', course_id=course.id)

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

        with transaction.atomic():
            Course.objects.select_for_update().get(pk=course.pk)
            # Auto-calculate order (max + 1)
            max_order = Section.objects.filter(course=course).aggregate(
                models.Max('order')
            )['order__max']
            new_order = (max_order if max_order is not None else -1) + 1

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

        with transaction.atomic():
            Course.objects.select_for_update().get(pk=course.pk)
            # Auto-calculate order (max + 1)
            max_order = Episode.objects.filter(section=section).aggregate(
                models.Max('order')
            )['order__max']
            new_order = (max_order if max_order is not None else -1) + 1

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
        episode.info_page_content = request.POST.get('info_page_content', '')
        if episode.type == 'quiz':
            # Browser form encoding converts textarea LF to CRLF. Keep the
            # persisted quiz format canonical as well as tolerating old data.
            episode.info_page_content = episode.info_page_content.replace(
                '\r\n', '\n'
            ).replace('\r', '\n')

        # Handle PDF uploads with validation
        if 'content_pdf' in request.FILES:
            pdf_file = request.FILES['content_pdf']
            if validate_pdf(pdf_file):
                episode.content_pdf = pdf_file
            else:
                messages.error(request, 'Invalid PDF file for content.')

        if 'answer_pdf' in request.FILES and episode.type == 'paper':
            pdf_file = request.FILES['answer_pdf']
            if validate_pdf(pdf_file):
                episode.answer_pdf = pdf_file
            else:
                messages.error(request, 'Invalid PDF file for answers.')

        # Quiz configuration toggles
        episode.quiz_require_all = request.POST.get('quiz_require_all') == 'on'
        release_policy = request.POST.get('quiz_release_policy', 'inherit')
        if release_policy in dict(Episode.QUIZ_RELEASE_CHOICES):
            episode.quiz_release_policy = release_policy

        # Code episode layout toggles
        episode.show_interactive = request.POST.get('show_interactive') == 'on'
        episode.show_reference = request.POST.get('show_reference') == 'on'

        # Automated code testing configuration
        episode.code_oj_enabled = request.POST.get('code_oj_enabled') == 'on'
        episode.code_oj_testcases = request.POST.get('code_oj_testcases', '[]')

        # Starter code
        episode.starter_code = request.POST.get('starter_code', '')

        # Reference sheet
        episode.reference_sheet_content = request.POST.get('reference_sheet_content', '')

        episode.save()
        messages.success(request, f'Episode "{episode.title}" updated successfully!')
        return redirect('teacher:course_edit', course_id=course.id)

    context = {
        'episode': episode,
        'course': course,
        'type_options': Episode.TYPE_CHOICES,
        'release_policy_options': Episode.QUIZ_RELEASE_CHOICES,
    }
    return render(request, 'teacher/episode_edit.html', context)


@teacher_required
@require_POST
def tag_create(request):
    """Create a new tag via AJAX."""
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
        logger.error("Tag creation failed: %s", e)
        return JsonResponse({'success': False, 'error': 'Failed to create tag.'})


def _reorder_content(request, content_model, payload_key):
    """Save one complete sibling ordering atomically, after ownership validation."""
    try:
        data = json.loads(request.body)
        items = data.get(payload_key) if isinstance(data, dict) else None
        if not isinstance(items, list) or not items or len(items) > 5000:
            raise ValueError('Provide the complete list to reorder.')
        if any(
            not isinstance(item, dict)
            or type(item.get('id')) is not int
            or type(item.get('order')) is not int
            for item in items
        ):
            raise ValueError('Invalid ordering data.')
        ids = [item['id'] for item in items]
        if len(set(ids)) != len(ids) or sorted(item['order'] for item in items) != list(range(len(items))):
            raise ValueError('Ordering must contain each item exactly once.')
    except (json.JSONDecodeError, ValueError) as error:
        return JsonResponse({'success': False, 'error': str(error)}, status=400)

    with transaction.atomic():
        objects = list(content_model.objects.filter(pk__in=ids))
        if len(objects) != len(ids):
            return JsonResponse({'success': False, 'error': 'Content changed. Reload and try again.'}, status=409)
        parent_field = 'course_id' if content_model is Section else 'section_id'
        parent_ids = {getattr(obj, parent_field) for obj in objects}
        if len(parent_ids) != 1:
            return JsonResponse({'success': False, 'error': 'Items must belong to the same parent.'}, status=400)
        course_id = objects[0].course_id if content_model is Section else objects[0].section.course_id
        course = Course.objects.select_for_update().get(pk=course_id)
        if not request.user.is_admin and course.creator_id != request.user.pk:
            return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
        siblings = content_model.objects.filter(**{parent_field: parent_ids.pop()})
        if set(siblings.values_list('pk', flat=True)) != set(ids):
            return JsonResponse({'success': False, 'error': 'Content changed. Reload and try again.'}, status=409)
        orders = {item['id']: item['order'] for item in items}
        for obj in objects:
            obj.order = orders[obj.pk]
        content_model.objects.bulk_update(objects, ['order'])
    return JsonResponse({'success': True})


@teacher_required
@require_POST
def section_reorder(request):
    return _reorder_content(request, Section, 'section_orders')


@teacher_required
@require_POST
def episode_reorder(request):
    return _reorder_content(request, Episode, 'episode_orders')


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


# ========== Course Management ==========

@login_required
@teacher_required
@require_course_ownership
def course_manage(request, course_id):
    """Teacher dashboard: student progress, enrollment management, assignments."""
    course = request.course

    # Get all enrolled students
    enrollments = CourseEnrollment.objects.filter(
        course=course
    ).select_related('user').order_by('-enrolled_at')

    # Total episodes for progress calculation
    total_episodes = Episode.objects.filter(section__course=course).count()

    # Calculate progress for each student
    students_data = []
    progress_values = []

    for enrollment in enrollments:
        if total_episodes > 0:
            read_count = EpisodeReadStatus.objects.filter(
                user=enrollment.user,
                episode__section__course=course,
                is_read=True
            ).count()
            progress_pct = int((read_count / total_episodes) * 100)
        else:
            read_count = 0
            progress_pct = 0

        progress_values.append(progress_pct)

        students_data.append({
            'user': enrollment.user,
            'enrolled_at': enrollment.enrolled_at,
            'read_episodes': read_count,
            'total_episodes': total_episodes,
            'progress_pct': progress_pct,
        })

    # Overall stats (box plot: min, Q1, median, Q3, max)
    if progress_values:
        sorted_vals = sorted(progress_values)
        n = len(sorted_vals)

        def percentile(data, p):
            """Linear interpolation percentile (0–100)."""
            k = (len(data) - 1) * p / 100
            f = int(k)
            c = k - f
            if f + 1 < len(data):
                return data[f] + c * (data[f + 1] - data[f])
            return data[f]

        _min = sorted_vals[0]
        _q1 = round(percentile(sorted_vals, 25))
        _median = round(percentile(sorted_vals, 50))
        _q3 = round(percentile(sorted_vals, 75))
        _max = sorted_vals[-1]

        stats = {
            'min': _min, 'q1': _q1, 'median': _median, 'q3': _q3, 'max': _max,
            'whisker_width': _max - _min,
            'box_width': _q3 - _q1,
            'show_q1': (_median - _q1) >= 5,
            'show_q3': (_q3 - _median) >= 5,
            'total_students': len(students_data),
        }
    else:
        stats = {
            'min': 0, 'q1': 0, 'median': 0, 'q3': 0, 'max': 0,
            'whisker_width': 0, 'box_width': 0,
            'show_q1': False, 'show_q3': False,
            'total_students': 0,
        }

    # Get quiz and code episodes with submission counts
    quiz_episodes = []
    assignable_types = ['quiz', 'code']
    for ep in Episode.objects.filter(
        section__course=course, type__in=assignable_types
    ).select_related('section'):
        if ep.type == 'quiz':
            count = QuizSubmission.objects.filter(episode=ep).count()
        else:
            count = CodeSubmission.objects.filter(
                episode=ep, is_submitted=True
            ).count()
        quiz_episodes.append({
            'id': ep.id,
            'title': ep.title,
            'section': ep.section,
            'type': ep.type,
            'submission_count': count,
        })

    context = {
        'course': course,
        'students_data': students_data,
        'stats': stats,
        'quiz_episodes': quiz_episodes,
    }
    return render(request, 'teacher/course_manage.html', context)


@login_required
@teacher_required
@require_POST
def remove_student(request):
    """Remove a student from a course (teacher only)."""
    course_id = request.POST.get('course_id')
    user_id = request.POST.get('user_id')

    if not course_id or not user_id:
        return JsonResponse({'success': False, 'error': 'Missing parameters'})

    course = get_object_or_404(Course, id=course_id)

    # Ownership check
    if not request.user.is_admin and course.creator != request.user:
        return JsonResponse({'success': False, 'error': 'Permission denied'})

    enrollment = CourseEnrollment.objects.filter(
        course=course, user_id=user_id
    ).first()

    if enrollment:
        enrollment.delete()
        return JsonResponse({'success': True, 'message': 'Student removed successfully.'})
    else:
        return JsonResponse({'success': False, 'error': 'Student is not enrolled in this course.'})


# ========== Assignment Review ==========


def _normalize_choice_ids(value, choice_count):
    """Return valid integer choice IDs from a stored quiz answer."""
    if not isinstance(value, list):
        return []
    return [
        choice_id for choice_id in value
        if type(choice_id) is int and 0 <= choice_id < choice_count
    ]


def _normalize_cba_token_lines(value, quiz_question):
    """Validate a CBA answer without trusting client-provided token IDs."""
    expected_lines = quiz_question.get('lines', [])
    if not isinstance(value, list) or len(value) != len(expected_lines):
        return None

    allowed_ids = {
        choice['id'] for choice in quiz_question.get('choices', [])
        if not choice.get('hint')
    }
    seen_ids = set()
    normalized = []
    for line in value:
        if not isinstance(line, list):
            return None
        normalized_line = []
        for token_id in line:
            if (
                not isinstance(token_id, str)
                or token_id not in allowed_ids
                or token_id in seen_ids
            ):
                return None
            seen_ids.add(token_id)
            normalized_line.append(token_id)
        normalized.append(normalized_line)
    return normalized


def _cba_tokens_equivalent(actual, expected):
    """Compare displayed code, not the identity of a token-bank occurrence.

    Boundary padding is invisible on code cards; internal whitespace (including
    strings), indentation cards, and indentation merged into code remain exact.
    """
    if not actual or not expected or actual.get('kind') != expected.get('kind'):
        return False
    if actual.get('kind') == 'indent':
        return actual['text'] == expected['text']
    return (
        actual.get('leadingIndent', '') == expected.get('leadingIndent', '')
        and actual['text'].strip(' \t') == expected['text'].strip(' \t')
    )


def _is_cba_answer_correct(quiz_question, value):
    token_lines = _normalize_cba_token_lines(value, quiz_question)
    if token_lines is None:
        return False
    choices_by_id = {choice['id']: choice for choice in quiz_question['choices']}
    for line, submitted_ids in zip(quiz_question['lines'], token_lines):
        expected = [choice for choice in line['choices'] if not choice['hint']]
        if len(submitted_ids) != len(expected):
            return False
        if not all(
            _cba_tokens_equivalent(choices_by_id[token_id], choice)
            for token_id, choice in zip(submitted_ids, expected)
        ):
            return False
    return True


def _build_cba_review_lines(quiz_question, token_lines):
    """Place movable answers into the fixed hint slots used by the CBA UI."""
    choices_by_id = {
        choice['id']: choice for choice in quiz_question.get('choices', [])
    }
    review_lines = []
    for line_index, line_definition in enumerate(quiz_question.get('lines', [])):
        correct_choices = [
            choices_by_id[token_id]
            for token_id in line_definition.get('choiceIds', [])
            if token_id in choices_by_id
        ]
        submitted_ids = token_lines[line_index] if token_lines is not None else []
        submitted_iter = iter(submitted_ids)
        rendered_tokens = []

        for expected_choice in correct_choices:
            if expected_choice.get('hint'):
                rendered = expected_choice.copy()
                rendered['positionCorrect'] = True
            else:
                submitted_id = next(submitted_iter, None)
                if submitted_id is None:
                    continue
                rendered = choices_by_id[submitted_id].copy()
                rendered['positionCorrect'] = _cba_tokens_equivalent(
                    rendered, expected_choice
                )
            rendered_tokens.append(rendered)

        # A malformed/incomplete row can contain more tokens than its own line.
        # Preserve those known tokens in the review instead of hiding the error.
        for submitted_id in submitted_iter:
            rendered = choices_by_id[submitted_id].copy()
            rendered['positionCorrect'] = False
            rendered_tokens.append(rendered)

        review_lines.append({
            'number': line_index + 1,
            'tokens': rendered_tokens,
            'empty': not rendered_tokens,
        })
    return review_lines


@login_required
@teacher_required
def assignment_review(request, course_id, episode_id):
    """Review submissions for quiz or code episodes."""
    course = get_object_or_404(Course, id=course_id)
    episode = get_object_or_404(Episode, id=episode_id, section__course=course)

    if episode.type not in ('quiz', 'code'):
        raise PermissionDenied("This episode type does not support assignment review.")

    # Ownership check
    if not request.user.is_admin and course.creator != request.user:
        raise PermissionDenied("You can only review your own course content.")

    # Get all enrolled students and their submissions
    enrollments = CourseEnrollment.objects.filter(course=course).select_related('user')

    if episode.type == 'quiz':
        submissions_by_user = {
            s.user_id: s for s in QuizSubmission.objects.filter(episode=episode)
        }
    else:
        submissions_by_user = {
            s.user_id: s for s in CodeSubmission.objects.filter(
                episode=episode, is_submitted=True
            )
        }

    students = []
    for enrollment in enrollments:
        sub = submissions_by_user.get(enrollment.user_id)
        students.append({
            'user': enrollment.user,
            'submitted': sub is not None,
            'submission': sub,
        })

    # Determine selected student's submission
    selected_user_id = request.GET.get('user_id')
    selected_submission = None
    if selected_user_id:
        selected_submission = submissions_by_user.get(int(selected_user_id))

    # If no selection, pick first submitted student
    if not selected_submission:
        for s in students:
            if s['submitted']:
                selected_submission = s['submission']
                break

    # Parse content and build review data based on episode type
    import json

    if episode.type == 'quiz':
        # --- Quiz review logic (existing) ---
        quiz_content = episode.info_page_content or ''
        quiz_questions = _parse_quiz_markdown(quiz_content)

        frq_grades = {}
        selected_questions = None
        all_frq_graded = True

        if selected_submission:
            if selected_submission.frq_grades:
                try:
                    frq_grades = json.loads(selected_submission.frq_grades)
                    if not isinstance(frq_grades, dict):
                        frq_grades = {}
                except json.JSONDecodeError:
                    frq_grades = {}

            if selected_submission.answers:
                try:
                    selected_answers = json.loads(selected_submission.answers)
                except json.JSONDecodeError:
                    selected_answers = None
            else:
                selected_answers = None

            if isinstance(selected_answers, dict):
                answer_list = selected_answers.get('questions', [])
                if not isinstance(answer_list, list):
                    answer_list = []
                selected_questions = []
                has_frq = False
                for i, quiz_q in enumerate(quiz_questions):
                    student_ans = answer_list[i] if i < len(answer_list) else {}
                    if not isinstance(student_ans, dict):
                        student_ans = {}
                    choice_count = len(quiz_q['choices'])
                    selected_index = student_ans.get('selectedIndex')
                    if (
                        type(selected_index) is not int
                        or not 0 <= selected_index < choice_count
                    ):
                        selected_index = None
                    selected_ids = _normalize_choice_ids(
                        student_ans.get('selectedIds'), choice_count
                    )
                    merged = {
                        'index': i,
                        'type': quiz_q['type'],
                        'question_html': quiz_q['question'],
                        'choices': quiz_q['choices'],
                        'student_answer': student_ans,
                        'refAnswer': quiz_q.get('refAnswer', ''),
                    }
                    letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                    for j, c in enumerate(quiz_q['choices']):
                        c['letter'] = letters[j] if j < len(letters) else str(j)
                        if quiz_q['type'] == 'mcq':
                            c['isSelected'] = selected_index == j
                        elif quiz_q['type'] == 'mrq':
                            c['isSelected'] = j in selected_ids
                        if quiz_q['type'] in ('mcq', 'mrq'):
                            if c['isSelected']:
                                result_class = (
                                    'correct' if c.get('isCorrect')
                                    else 'wrong-student'
                                )
                                c['rowClass'] = f'student-selected {result_class}'
                            elif c.get('isCorrect'):
                                c['rowClass'] = 'correct-answer'
                            else:
                                c['rowClass'] = ''

                    if quiz_q['type'] == 'mcq':
                        merged['is_correct'] = (
                            selected_index is not None
                            and quiz_q['choices'][selected_index]['isCorrect']
                        )
                    elif quiz_q['type'] == 'mrq':
                        correct_ids = {j for j, c in enumerate(quiz_q['choices']) if c.get('isCorrect')}
                        merged['is_correct'] = set(selected_ids) == correct_ids
                    elif quiz_q['type'] == 'srt':
                        correct_order = sorted(
                            range(len(quiz_q['choices'])),
                            key=lambda choice_index: quiz_q['choices'][
                                choice_index
                            ].get('sortPosition', choice_index + 1),
                        )
                        merged['is_correct'] = selected_ids == correct_order
                        merged['student_choices'] = []
                        for position, choice_index in enumerate(
                            selected_ids, start=1
                        ):
                            student_choice = quiz_q['choices'][choice_index].copy()
                            student_choice['studentPos'] = position
                            student_choice['positionCorrect'] = (
                                student_choice.get('sortPosition') == position
                            )
                            merged['student_choices'].append(student_choice)
                    elif quiz_q['type'] == 'cba':
                        token_lines = _normalize_cba_token_lines(
                            student_ans.get('tokenIds'), quiz_q
                        )
                        merged['is_correct'] = _is_cba_answer_correct(
                            quiz_q, token_lines
                        )
                        merged['student_lines'] = _build_cba_review_lines(
                            quiz_q, token_lines
                        )
                        merged['answer_valid'] = token_lines is not None
                        merged['language'] = quiz_q.get('language', '')
                    elif quiz_q['type'] == 'frq':
                        has_frq = True
                        merged['frq_graded'] = str(i) in frq_grades
                        merged['frq_correct'] = frq_grades.get(str(i), None)
                        if not merged['frq_graded']:
                            all_frq_graded = False
                    selected_questions.append(merged)
                if not has_frq:
                    all_frq_graded = True

        context = {
            'course': course,
            'episode': episode,
            'students': students,
            'selected_submission': selected_submission,
            'selected_questions': selected_questions,
            'frq_grades': frq_grades,
            'all_frq_graded': all_frq_graded,
        }

    else:
        # --- Code review logic ---
        selected_code = ''
        test_results = []
        oj_enabled = getattr(episode, 'code_oj_enabled', False)
        oj_testcases_raw = getattr(episode, 'code_oj_testcases', '[]')

        if selected_submission:
            selected_code = selected_submission.code or ''
            if selected_submission.test_results:
                try:
                    test_results = validate_test_results(json.loads(selected_submission.test_results))
                except (json.JSONDecodeError, ValueError):
                    test_results = []

        # Count passed test cases
        passed_count = sum(1 for tr in test_results if tr.get('passed'))
        total_count = len(test_results) if test_results else 0

        context = {
            'course': course,
            'episode': episode,
            'students': students,
            'selected_submission': selected_submission,
            'selected_code': selected_code,
            'test_results': test_results,
            'passed_count': passed_count,
            'total_count': total_count,
            'oj_enabled': oj_enabled,
        }

    context['submission_version'] = selected_submission.submitted_at.isoformat() if selected_submission and selected_submission.submitted_at else ''
    return render(request, 'teacher/assignment_review.html', context)


def _review_submission(request):
    try:
        submission_id = int(request.POST.get('submission_id', ''))
    except (TypeError, ValueError):
        return None, JsonResponse({'success': False, 'error': 'Invalid submission ID'}, status=400)
    submission = get_object_or_404(QuizSubmission.objects.select_for_update(), pk=submission_id)
    if not request.user.is_admin and submission.episode.section.course.creator_id != request.user.pk:
        return None, JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
    if request.POST.get('submission_version') != submission.submitted_at.isoformat():
        return None, JsonResponse({
            'success': False, 'error': 'The submission changed. Reload before reviewing it.'
        }, status=409)
    return submission, None


@login_required
@teacher_required
@require_POST
@transaction.atomic
def grade_frq(request):
    """Grade a FRQ answer in a submission."""
    submission_id = request.POST.get('submission_id')
    question_index = request.POST.get('question_index')
    is_correct = request.POST.get('is_correct') == 'true'

    if not submission_id or question_index is None:
        return JsonResponse({'success': False, 'error': 'Missing parameters'})

    submission, error_response = _review_submission(request)
    if error_response:
        return error_response

    import json
    try:
        grades = json.loads(submission.frq_grades) if submission.frq_grades else {}
    except json.JSONDecodeError:
        grades = {}

    questions = _parse_quiz_markdown(submission.episode.info_page_content or '')
    try:
        question_index = int(question_index)
        if not 0 <= question_index < len(questions) or questions[question_index]['type'] != 'frq':
            raise ValueError
        if request.POST.get('is_correct') not in ('true', 'false'):
            raise ValueError
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid FRQ grade'}, status=400)
    if not isinstance(grades, dict):
        grades = {}
    grades[str(question_index)] = is_correct
    submission.frq_grades = json.dumps(grades)
    submission.save(update_fields=['frq_grades'])

    return JsonResponse({'success': True, 'is_correct': is_correct})


@login_required
@teacher_required
@require_POST
@transaction.atomic
def release_submission(request):
    """Release a submission back to the student."""
    submission_id = request.POST.get('submission_id')

    if not submission_id:
        return JsonResponse({'success': False, 'error': 'Missing submission ID'})

    submission, error_response = _review_submission(request)
    if error_response:
        return error_response

    try:
        grades = json.loads(submission.frq_grades)
    except (json.JSONDecodeError, TypeError):
        grades = {}
    if not isinstance(grades, dict):
        grades = {}
    questions = _parse_quiz_markdown(submission.episode.info_page_content or '')
    if any(q['type'] == 'frq' and type(grades.get(str(i))) is not bool for i, q in enumerate(questions)):
        return JsonResponse({'success': False, 'error': 'All FRQ questions must be graded before releasing.'}, status=400)

    submission.released_at = timezone.now()
    submission.save(update_fields=['released_at'])

    return JsonResponse({'success': True, 'message': 'Submission released to student.'})


@login_required
@teacher_required
@require_POST
@transaction.atomic
def cancel_release(request):
    """Cancel a release — reverts submission back to unreleased state."""
    submission_id = request.POST.get('submission_id')
    if not submission_id:
        return JsonResponse({'success': False, 'error': 'Missing submission ID'})

    submission, error_response = _review_submission(request)
    if error_response:
        return error_response

    submission.released_at = None
    submission.save(update_fields=['released_at'])

    return JsonResponse({'success': True, 'message': 'Release cancelled.'})


@login_required
@teacher_required
@require_POST
@transaction.atomic
def reset_submission(request):
    """Reset a student's submission — deletes it so the student can redo."""
    submission_id = request.POST.get('submission_id')
    if not submission_id:
        return JsonResponse({'success': False, 'error': 'Missing submission ID'})

    submission, error_response = _review_submission(request)
    if error_response:
        return error_response

    # Keep references before delete
    episode = submission.episode
    user = submission.user
    submission.delete()

    # Mark episode as unread since submission is reset
    EpisodeReadStatus.objects.filter(user=user, episode=episode).update(is_read=False)

    return JsonResponse({'success': True, 'message': 'Submission reset. Student can redo the quiz.'})

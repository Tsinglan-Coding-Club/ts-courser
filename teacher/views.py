from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db import models
from courses.models import Course, Section, Episode, Tag
from progress.models import CourseEnrollment, EpisodeReadStatus, QuizSubmission
from .decorators import (
    teacher_required,
    require_course_ownership,
    require_episode_ownership,
    check_section_ownership,
)
import logging
import magic
import os

from ts_courser.utils import compress_image

logger = logging.getLogger(__name__)


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
        new_mode = request.POST.get('enrollment_mode')
        if new_mode in ('open', 'code'):
            course.enrollment_mode = new_mode
        course.enrollment_open = request.POST.get('enrollment_open') == 'on'
        course.auto_release_results = request.POST.get('auto_release_results') == 'on'
        tag_ids = request.POST.getlist('tags')

        # Regenerate course code if requested (only in code mode)
        if request.POST.get('regenerate_code') == '1' and course.enrollment_mode == 'code':
            course.course_code = course._generate_code()

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

        if 'answer_pdf' in request.FILES and episode.type == 'paper':
            pdf_file = request.FILES['answer_pdf']
            if validate_pdf(pdf_file):
                episode.answer_pdf = pdf_file
            else:
                messages.error(request, 'Invalid PDF file for answers.')

        # Quiz configuration toggles
        episode.quiz_require_all = request.POST.get('quiz_require_all') == 'on'
        episode.quiz_show_results = request.POST.get('quiz_show_results') == 'on'

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

    # Get quiz episodes with submission counts
    quiz_episodes = []
    for ep in Episode.objects.filter(section__course=course, type='quiz').select_related('section'):
        count = QuizSubmission.objects.filter(episode=ep).count()
        quiz_episodes.append({
            'id': ep.id,
            'title': ep.title,
            'section': ep.section,
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

@login_required
@teacher_required
def assignment_review(request, course_id, episode_id):
    """Review quiz submissions for a specific episode."""
    course = get_object_or_404(Course, id=course_id)
    episode = get_object_or_404(Episode, id=episode_id, section__course=course, type='quiz')

    # Ownership check
    if not request.user.is_admin and course.creator != request.user:
        raise PermissionDenied("You can only review your own course content.")

    # Get all enrolled students and their submissions
    enrollments = CourseEnrollment.objects.filter(course=course).select_related('user')
    submissions_by_user = {
        s.user_id: s for s in QuizSubmission.objects.filter(episode=episode)
    }

    students = []
    for enrollment in enrollments:
        sub = submissions_by_user.get(enrollment.user_id)
        students.append({
            'user': enrollment.user,
            'submitted': sub is not None,
            'submission': sub,
        })

    # Parse quiz content for display
    quiz_content = episode.info_page_content or ''
    quiz_questions = _parse_quiz_markdown(quiz_content)

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

    # Parse FRQ grades and student answers, merge with quiz data
    frq_grades = {}
    selected_questions = None
    all_frq_graded = True

    if selected_submission:
        import json
        if selected_submission.frq_grades:
            try:
                frq_grades = json.loads(selected_submission.frq_grades)
            except json.JSONDecodeError:
                frq_grades = {}

        if selected_submission.answers:
            try:
                selected_answers = json.loads(selected_submission.answers)
            except json.JSONDecodeError:
                selected_answers = None
        else:
            selected_answers = None

        # Merge quiz questions with student answers
        if selected_answers:
            answer_list = selected_answers.get('questions', [])
            selected_questions = []
            has_frq = False
            for i, quiz_q in enumerate(quiz_questions):
                student_ans = answer_list[i] if i < len(answer_list) else {}
                merged = {
                    'index': i,
                    'type': quiz_q['type'],
                    'question_html': quiz_q['question'],
                    'choices': quiz_q['choices'],
                    'student_answer': student_ans,
                    'refAnswer': quiz_q.get('refAnswer', ''),
                }
                # Pre-compute choice display data
                letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                for j, c in enumerate(quiz_q['choices']):
                    c['letter'] = letters[j] if j < len(letters) else str(j)
                    if quiz_q['type'] == 'mcq':
                        c['isSelected'] = (student_ans.get('selectedIndex') == j)
                        c['rowClass'] = 'correct' if c.get('isCorrect') else ('wrong-student' if c['isSelected'] else '')
                    elif quiz_q['type'] == 'mrq':
                        sids = student_ans.get('selectedIds', []) or []
                        c['isSelected'] = j in sids
                        c['rowClass'] = 'correct' if c.get('isCorrect') else ('wrong-student' if c['isSelected'] else '')
                    elif quiz_q['type'] == 'srt':
                        sids = student_ans.get('selectedIds', []) or []
                        try:
                            c['studentPos'] = sids.index(j) + 1
                        except (ValueError, IndexError):
                            c['studentPos'] = 0

                # Determine correctness per type
                if quiz_q['type'] == 'mcq':
                    si = student_ans.get('selectedIndex')
                    merged['is_correct'] = (
                        si is not None and
                        any(c['isCorrect'] for j, c in enumerate(quiz_q['choices']) if j == si)
                    )
                elif quiz_q['type'] == 'mrq':
                    sids = student_ans.get('selectedIds', []) or []
                    correct_ids = {j for j, c in enumerate(quiz_q['choices']) if c.get('isCorrect')}
                    merged['is_correct'] = set(sids) == correct_ids
                elif quiz_q['type'] == 'srt':
                    sids = student_ans.get('selectedIds', []) or []
                    correct_order = [c.get('sortPosition', j+1) - 1 for j, c in enumerate(quiz_q['choices'])]
                    merged['is_correct'] = sids == correct_order
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
    return render(request, 'teacher/assignment_review.html', context)


def _parse_quiz_markdown(md):
    """Parse quiz markdown into structured question objects (mirrors JS parser)."""
    import re
    if not md or not md.strip():
        return []

    blocks = re.split(r'^## (?![#])', md, flags=re.MULTILINE)
    questions = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.split('\n')

        first_choice = -1
        for j, line in enumerate(lines):
            if re.match(r'^>', line):
                first_choice = j
                break

        if first_choice == -1:
            question_text = '\n'.join(lines).strip()
            choice_lines = []
        else:
            question_text = '\n'.join(lines[:first_choice]).strip()
            choice_lines = lines[first_choice:]

        if not question_text:
            continue

        choices = []
        has_mrq = False
        has_sort = False

        for line in choice_lines:
            m_frq_ref = re.match(r'^>= (.+)$', line)
            m_frq_e = re.match(r'^>=\s*$', line)
            m_mcq = re.match(r'^>\+ (.+)$', line)
            m_mcq_e = re.match(r'^>\+\s*$', line)
            m_mrq = re.match(r'^>\* (.+)$', line)
            m_mrq_e = re.match(r'^>\*\s*$', line)
            m_sort = re.match(r'^>(\d+)(?:\s+(.+))?$', line)
            m_wrong = re.match(r'^> (?!\+)(?!\*)(.+)$', line)
            m_empty = re.match(r'^>\s*$', line)

            if m_frq_ref:
                choices.append({'text': m_frq_ref.group(1).strip(), 'isCorrect': False, 'isFRQRef': True})
            elif m_frq_e:
                choices.append({'text': '', 'isCorrect': False, 'isFRQRef': True})
            elif m_mcq:
                choices.append({'text': m_mcq.group(1).strip(), 'isCorrect': True})
            elif m_mcq_e:
                choices.append({'text': '', 'isCorrect': True})
            elif m_mrq:
                choices.append({'text': m_mrq.group(1).strip(), 'isCorrect': True})
                has_mrq = True
            elif m_mrq_e:
                choices.append({'text': '', 'isCorrect': True})
                has_mrq = True
            elif m_sort:
                choices.append({
                    'text': m_sort.group(2).strip() if m_sort.group(2) else '',
                    'isCorrect': False,
                    'sortPosition': int(m_sort.group(1))
                })
                has_sort = True
            elif m_wrong:
                choices.append({'text': m_wrong.group(1).strip(), 'isCorrect': False})
            elif m_empty:
                choices.append({'text': '', 'isCorrect': False})

        is_frq = (len(choices) == 0
                  or (len(choices) == 1 and choices[0]['text'] == '')
                  or (len(choices) == 1 and choices[0].get('isFRQRef')))
        ref_answer = ''
        if is_frq and len(choices) == 1 and choices[0].get('isFRQRef'):
            ref_answer = choices[0]['text']
        if is_frq:
            qtype = 'frq'
        elif has_sort:
            qtype = 'srt'
        elif has_mrq:
            qtype = 'mrq'
        else:
            qtype = 'mcq'

        questions.append({
            'type': qtype,
            'question': question_text,
            'choices': [] if is_frq else choices,
            'refAnswer': ref_answer,
        })

    return questions


@login_required
@teacher_required
@require_POST
def grade_frq(request):
    """Grade a FRQ answer in a submission."""
    submission_id = request.POST.get('submission_id')
    question_index = request.POST.get('question_index')
    is_correct = request.POST.get('is_correct') == 'true'

    if not submission_id or question_index is None:
        return JsonResponse({'success': False, 'error': 'Missing parameters'})

    submission = get_object_or_404(QuizSubmission, id=submission_id)
    course = submission.episode.section.course

    if not request.user.is_admin and course.creator != request.user:
        return JsonResponse({'success': False, 'error': 'Permission denied'})

    import json
    try:
        grades = json.loads(submission.frq_grades) if submission.frq_grades else {}
    except json.JSONDecodeError:
        grades = {}

    grades[str(question_index)] = is_correct
    submission.frq_grades = json.dumps(grades)
    submission.save(update_fields=['frq_grades'])

    return JsonResponse({'success': True, 'is_correct': is_correct})


@login_required
@teacher_required
@require_POST
def release_submission(request):
    """Release a submission back to the student."""
    submission_id = request.POST.get('submission_id')

    if not submission_id:
        return JsonResponse({'success': False, 'error': 'Missing submission ID'})

    submission = get_object_or_404(QuizSubmission, id=submission_id)
    course = submission.episode.section.course

    if not request.user.is_admin and course.creator != request.user:
        return JsonResponse({'success': False, 'error': 'Permission denied'})

    # Check all FRQs are graded
    if submission.answers:
        import json
        try:
            answers = json.loads(submission.answers)
            grades = json.loads(submission.frq_grades) if submission.frq_grades else {}
            for i, q in enumerate(answers.get('questions', [])):
                if q.get('type') == 'frq' and str(i) not in grades:
                    return JsonResponse({
                        'success': False,
                        'error': 'All FRQ questions must be graded before releasing.'
                    })
        except json.JSONDecodeError:
            pass

    submission.released_at = timezone.now()
    submission.save(update_fields=['released_at'])

    return JsonResponse({'success': True, 'message': 'Submission released to student.'})


@login_required
@teacher_required
@require_POST
def cancel_release(request):
    """Cancel a release — reverts submission back to unreleased state."""
    submission_id = request.POST.get('submission_id')
    if not submission_id:
        return JsonResponse({'success': False, 'error': 'Missing submission ID'})

    submission = get_object_or_404(QuizSubmission, id=submission_id)
    course = submission.episode.section.course

    if not request.user.is_admin and course.creator != request.user:
        return JsonResponse({'success': False, 'error': 'Permission denied'})

    submission.released_at = None
    submission.save(update_fields=['released_at'])

    return JsonResponse({'success': True, 'message': 'Release cancelled.'})


@login_required
@teacher_required
@require_POST
def reset_submission(request):
    """Reset a student's submission — deletes it so the student can redo."""
    submission_id = request.POST.get('submission_id')
    if not submission_id:
        return JsonResponse({'success': False, 'error': 'Missing submission ID'})

    submission = get_object_or_404(QuizSubmission, id=submission_id)
    course = submission.episode.section.course

    if not request.user.is_admin and course.creator != request.user:
        return JsonResponse({'success': False, 'error': 'Permission denied'})

    # Keep references before delete
    episode = submission.episode
    user = submission.user
    submission.delete()

    # Mark episode as unread since submission is reset
    EpisodeReadStatus.objects.filter(user=user, episode=episode).update(is_read=False)

    return JsonResponse({'success': True, 'message': 'Submission reset. Student can redo the quiz.'})

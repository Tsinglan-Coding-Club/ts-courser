"""Regression coverage for release hardening in teacher management views."""

from io import BytesIO
import json
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from accounts.models import User
from courses.models import Course, Episode, Section
from progress.models import CodeSubmission, CourseEnrollment, QuizSubmission


class TeacherReleaseRegressionTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='owner',
            email='owner@example.com',
            password='password',
            role='teacher',
            is_verified_teacher=True,
        )
        self.other_teacher = User.objects.create_user(
            username='other-owner',
            email='other@example.com',
            password='password',
            role='teacher',
            is_verified_teacher=True,
        )
        self.course = Course.objects.create(
            title='Owner course', description='Description', creator=self.teacher
        )
        self.client.force_login(self.teacher)

    def section(self, title, order=0, course=None):
        return Section.objects.create(
            course=course or self.course, title=title, order=order
        )

    def episode(self, section, title, order=0, episode_type='material'):
        return Episode.objects.create(
            section=section, title=title, type=episode_type, order=order
        )

    def post_json(self, url, payload):
        return self.client.post(
            url, data=json.dumps(payload), content_type='application/json'
        )

    def test_new_sections_and_episodes_append_after_initial_and_reordered_items(self):
        section_create_url = reverse('teacher:section_create')
        for title in ('First', 'Second'):
            response = self.client.post(
                section_create_url, {'course_id': self.course.id, 'title': title}
            )
            self.assertEqual(response.status_code, 302)
        sections = list(Section.objects.filter(course=self.course).order_by('order'))
        self.assertEqual([section.order for section in sections], [0, 1])

        response = self.post_json(
            reverse('teacher:section_reorder'),
            {'section_orders': [
                {'id': sections[0].id, 'order': 1},
                {'id': sections[1].id, 'order': 0},
            ]},
        )
        self.assertEqual(response.status_code, 200)
        self.client.post(
            section_create_url, {'course_id': self.course.id, 'title': 'Third'}
        )
        self.assertEqual(
            list(Section.objects.filter(course=self.course).values_list('order', flat=True).order_by('order')),
            [0, 1, 2],
        )

        episode_create_url = reverse('teacher:episode_create')
        target_section = Section.objects.get(course=self.course, title='First')
        for title in ('Episode one', 'Episode two'):
            response = self.client.post(
                episode_create_url, {'section_id': target_section.id, 'title': title}
            )
            self.assertEqual(response.status_code, 302)
        episodes = list(target_section.episodes.order_by('order'))
        self.assertEqual([episode.order for episode in episodes], [0, 1])

        response = self.post_json(
            reverse('teacher:episode_reorder'),
            {'episode_orders': [
                {'id': episodes[0].id, 'order': 1},
                {'id': episodes[1].id, 'order': 0},
            ]},
        )
        self.assertEqual(response.status_code, 200)
        self.client.post(
            episode_create_url,
            {'section_id': target_section.id, 'title': 'Episode three'},
        )
        self.assertEqual(
            list(target_section.episodes.values_list('order', flat=True).order_by('order')),
            [0, 1, 2],
        )

    def test_episode_edit_ignores_posted_order_and_hides_order_control(self):
        section = self.section('Section')
        episode = self.episode(section, 'Episode', order=3)
        url = reverse('teacher:episode_edit', args=[episode.id])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="order"')

        response = self.client.post(
            url,
            {
                'title': 'Edited episode',
                'type': 'material',
                'order': 999,
                'info_page_content': 'Updated',
            },
        )
        self.assertRedirects(response, reverse('teacher:course_edit', args=[self.course.id]))
        episode.refresh_from_db()
        self.assertEqual(episode.order, 3)
        self.assertEqual(episode.title, 'Edited episode')

    def test_section_reorder_rejects_non_owner_without_changes(self):
        first = self.section('First', 0)
        second = self.section('Second', 1)
        self.client.force_login(self.other_teacher)

        response = self.post_json(
            reverse('teacher:section_reorder'),
            {'section_orders': [
                {'id': first.id, 'order': 1}, {'id': second.id, 'order': 0},
            ]},
        )

        self.assertEqual(response.status_code, 403)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.order, second.order), (0, 1))

    def test_episode_reorder_rejects_mixed_sections_without_changes(self):
        first_section = self.section('First')
        second_section = self.section('Second')
        first = self.episode(first_section, 'First episode', 0)
        second = self.episode(second_section, 'Second episode', 0)

        response = self.post_json(
            reverse('teacher:episode_reorder'),
            {'episode_orders': [
                {'id': first.id, 'order': 0}, {'id': second.id, 'order': 1},
            ]},
        )

        self.assertEqual(response.status_code, 400)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.order, second.order), (0, 0))

    def test_reorder_rejects_malformed_duplicates_and_incomplete_sets_atomically(self):
        first = self.section('First', 0)
        second = self.section('Second', 1)
        url = reverse('teacher:section_reorder')
        invalid_payloads = [
            b'{not json',
            json.dumps({'section_orders': [
                {'id': first.id, 'order': 0}, {'id': first.id, 'order': 1},
            ]}),
            json.dumps({'section_orders': [
                {'id': first.id, 'order': 0}, {'id': second.id, 'order': 0},
            ]}),
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.client.post(url, data=payload, content_type='application/json')
                self.assertEqual(response.status_code, 400)
                first.refresh_from_db()
                second.refresh_from_db()
                self.assertEqual((first.order, second.order), (0, 1))

        response = self.post_json(
            url, {'section_orders': [{'id': first.id, 'order': 0}]}
        )
        self.assertEqual(response.status_code, 409)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.order, second.order), (0, 1))

    def test_successful_episode_reorder_persists_complete_sibling_order(self):
        section = self.section('Section')
        first = self.episode(section, 'First', 0)
        second = self.episode(section, 'Second', 1)
        third = self.episode(section, 'Third', 2)

        response = self.post_json(
            reverse('teacher:episode_reorder'),
            {'episode_orders': [
                {'id': first.id, 'order': 2},
                {'id': second.id, 'order': 0},
                {'id': third.id, 'order': 1},
            ]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {'success': True})
        self.assertEqual(
            list(section.episodes.order_by('order').values_list('title', flat=True)),
            ['Second', 'Third', 'First'],
        )

    def test_assignment_review_tolerates_legacy_invalid_code_test_results(self):
        section = self.section('Code section')
        episode = self.episode(section, 'Code episode', episode_type='code')
        student = User.objects.create_user(
            username='student', email='student@example.com', password='password'
        )
        CourseEnrollment.objects.create(user=student, course=self.course)
        submission = CodeSubmission.objects.create(
            user=student,
            episode=episode,
            code='print(1)',
            is_submitted=True,
        )
        url = reverse('teacher:assignment_review', args=[self.course.id, episode.id])

        for legacy_value in ('[1]', 'null', '{}'):
            with self.subTest(legacy_value=legacy_value):
                submission.test_results = legacy_value
                submission.save(update_fields=['test_results'])
                response = self.client.get(url, {'user_id': student.id})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['test_results'], [])

    def test_course_create_rejects_html_disguised_as_thumbnail(self):
        initial_count = Course.objects.filter(creator=self.teacher).count()
        response = self.client.post(
            reverse('teacher:course_create'),
            {
                'title': 'Unsafe thumbnail',
                'description': 'Should not create',
                'thumbnail': SimpleUploadedFile(
                    'thumbnail.png', b'<html>not an image</html>', 'image/png'
                ),
            },
        )

        self.assertRedirects(response, reverse('teacher:course_create'))
        self.assertEqual(Course.objects.filter(creator=self.teacher).count(), initial_count)

    def test_course_thumbnail_uploads_are_cropped_to_16_by_9(self):
        image_bytes = BytesIO()
        Image.new('RGB', (160, 160), 'green').save(image_bytes, format='PNG')
        upload = SimpleUploadedFile(
            'thumbnail.png', image_bytes.getvalue(), content_type='image/png'
        )

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                response = self.client.post(
                    reverse('teacher:course_create'),
                    {
                        'title': 'Cropped thumbnail',
                        'description': 'Description',
                        'thumbnail': upload,
                    },
                )

                course = Course.objects.get(title='Cropped thumbnail')
                self.assertRedirects(
                    response, reverse('teacher:course_edit', args=[course.id])
                )
                with Image.open(course.thumbnail.path) as thumbnail:
                    self.assertEqual(thumbnail.size, (160, 90))

    def create_frq_submission(self, answer='First answer'):
        section = self.section('FRQ section')
        episode = self.episode(section, 'FRQ episode', episode_type='quiz')
        episode.info_page_content = '## Explain your reasoning\n>= Reference answer'
        episode.quiz_release_policy = 'manual'
        episode.save(update_fields=['info_page_content', 'quiz_release_policy'])
        student = User.objects.create_user(
            username='frq-student', email='frq-student@example.com', password='password'
        )
        CourseEnrollment.objects.create(user=student, course=self.course)
        submission = QuizSubmission.objects.create(
            user=student,
            episode=episode,
            answers=json.dumps({'questions': [{'type': 'frq', 'text': answer}]}),
        )
        return student, episode, submission

    def test_current_submission_version_can_grade_and_release_an_actual_frq(self):
        _, _, submission = self.create_frq_submission()
        version = submission.submitted_at.isoformat()

        grade_response = self.client.post(
            reverse('teacher:grade_frq'),
            {
                'submission_id': submission.id,
                'submission_version': version,
                'question_index': '0',
                'is_correct': 'true',
            },
        )
        self.assertEqual(grade_response.status_code, 200)
        submission.refresh_from_db()
        self.assertEqual(json.loads(submission.frq_grades), {'0': True})

        release_response = self.client.post(
            reverse('teacher:release_submission'),
            {'submission_id': submission.id, 'submission_version': version},
        )
        self.assertEqual(release_response.status_code, 200)
        submission.refresh_from_db()
        self.assertIsNotNone(submission.released_at)

    def test_invalid_frq_index_is_rejected_without_changing_grades(self):
        _, _, submission = self.create_frq_submission()

        response = self.client.post(
            reverse('teacher:grade_frq'),
            {
                'submission_id': submission.id,
                'submission_version': submission.submitted_at.isoformat(),
                'question_index': '1',
                'is_correct': 'true',
            },
        )

        self.assertEqual(response.status_code, 400)
        submission.refresh_from_db()
        self.assertEqual(json.loads(submission.frq_grades), {})

    def test_stale_grade_and_release_do_not_affect_a_replaced_frq_answer(self):
        student, episode, submission = self.create_frq_submission('Original answer')
        stale_version = submission.submitted_at.isoformat()
        self.course.is_published = True
        self.course.save(update_fields=['is_published'])
        student_client = Client()
        student_client.force_login(student)

        replacement_response = student_client.post(
            reverse('progress:submit_quiz'),
            {
                'episode_id': episode.id,
                'answers': json.dumps({
                    'questions': [{'type': 'frq', 'text': 'Replacement answer'}],
                }),
            },
        )
        self.assertEqual(replacement_response.status_code, 200)
        submission.refresh_from_db()
        self.assertNotEqual(submission.submitted_at.isoformat(), stale_version)

        grade_response = self.client.post(
            reverse('teacher:grade_frq'),
            {
                'submission_id': submission.id,
                'submission_version': stale_version,
                'question_index': '0',
                'is_correct': 'true',
            },
        )
        release_response = self.client.post(
            reverse('teacher:release_submission'),
            {'submission_id': submission.id, 'submission_version': stale_version},
        )

        self.assertEqual(grade_response.status_code, 409)
        self.assertEqual(release_response.status_code, 409)
        submission.refresh_from_db()
        self.assertEqual(
            json.loads(submission.answers)['questions'][0]['text'], 'Replacement answer'
        )
        self.assertEqual(json.loads(submission.frq_grades), {})
        self.assertIsNone(submission.released_at)

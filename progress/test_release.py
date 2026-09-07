import json
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from courses.models import Course, Episode, Section
from courses.quiz import student_questions, token_id
from progress.models import CodeSubmission, CourseEnrollment, EpisodeReadStatus, QuizSubmission


class SubmissionValidationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='student', email='student@test.invalid')
        cls.course = Course.objects.create(title='Course', creator=cls.user, is_published=True)
        cls.section = Section.objects.create(title='Section', course=cls.course)
        cls.quiz = Episode.objects.create(
            title='Quiz', section=cls.section, type='quiz', quiz_release_policy='manual',
            info_page_content='## Choose\n>+ Yes\n> No',
        )
        cls.code = Episode.objects.create(title='Code', section=cls.section, type='code')
        CourseEnrollment.objects.create(user=cls.user, course=cls.course)

    def setUp(self):
        self.client.force_login(self.user)

    def submit(self, payload):
        return self.client.post(reverse('progress:submit_quiz'), {
            'episode_id': self.quiz.pk, 'answers': json.dumps(payload),
        })

    def test_invalid_code_results_do_not_replace_an_existing_submission(self):
        saved = CodeSubmission.objects.create(
            user=self.user, episode=self.code, code='original', is_submitted=True,
        )
        for value in (None, {}, [1], [{'passed': 'true'}], [{'passed': True, 'actual': []}]):
            with self.subTest(value=value):
                response = self.client.post(reverse('progress:submit_code'), {
                    'episode_id': self.code.pk, 'code': 'replacement',
                    'test_results': json.dumps(value),
                })
                self.assertEqual(response.status_code, 400)
                saved.refresh_from_db()
                self.assertEqual(saved.code, 'original')
        self.assertFalse(EpisodeReadStatus.objects.filter(user=self.user).exists())

    def test_required_answers_and_invalid_choices_are_rejected_for_all_types(self):
        cases = [
            ('## Pick\n>+ Yes\n> No', {'type': 'mcq'}),
            ('## Pick\n>+ Yes\n> No', {'type': 'mcq', 'selectedIndex': True}),
            ('## Pick\n>+ Yes\n> No', {'type': 'mcq', 'selectedIndex': 99}),
            ('## Pick\n>* Yes\n>* Also\n> No', {'type': 'mrq', 'selectedIds': []}),
            ('## Pick\n>* Yes\n>* Also\n> No', {'type': 'mrq', 'selectedIds': [0, 0]}),
            ('## Sort\n>2 Last\n>1 First', {'type': 'srt', 'selectedIds': [0]}),
            ('## Explain\n>= Reference', {'type': 'frq', 'text': '  '}),
            ('## Explain\n>= Reference', {'type': 'frq', 'text': {}}),
        ]
        for markdown, answer in cases:
            self.quiz.info_page_content = markdown
            self.quiz.save()
            with self.subTest(answer=answer):
                self.assertEqual(self.submit({'questions': [answer]}).status_code, 400)
        self.assertFalse(QuizSubmission.objects.exists())
        self.assertFalse(EpisodeReadStatus.objects.exists())

    def test_optional_blank_answer_is_valid_but_wrong_shape_is_not(self):
        self.quiz.quiz_require_all = False
        self.quiz.save()
        self.assertEqual(self.submit({'questions': [{'type': 'mcq'}]}).status_code, 200)
        for value in (None, [], {}, {'questions': {}}, {'questions': [None]}):
            self.assertEqual(self.submit(value).status_code, 400)

    def test_changed_frq_answer_clears_grade_and_manual_release(self):
        self.quiz.info_page_content = '## Explain\n>= Reference'
        self.quiz.save()
        original = {'questions': [{'type': 'frq', 'text': 'Old answer'}]}
        saved = QuizSubmission.objects.create(
            user=self.user, episode=self.quiz, answers=json.dumps(original),
            frq_grades='{"0": true}', released_at=timezone.now(),
        )
        old_date = saved.submitted_at
        self.assertEqual(self.submit(original).status_code, 200)
        saved.refresh_from_db()
        self.assertIsNotNone(saved.released_at)
        self.assertEqual(json.loads(saved.frq_grades), {'0': True})
        self.assertEqual(self.submit({'questions': [{'type': 'frq', 'text': 'New answer'}]}).status_code, 200)
        saved.refresh_from_db()
        self.assertIsNone(saved.released_at)
        self.assertEqual(json.loads(saved.frq_grades), {})
        self.assertGreater(saved.submitted_at, old_date)

    def test_cba_public_data_hides_solution_but_submissions_use_canonical_ids(self):
        self.quiz.info_page_content = '## Assemble\n```quiz-cba python\nprint("hi")\n```'
        self.quiz.save()
        public = student_questions(self.quiz)[0]
        self.assertNotIn('code', public)
        self.assertTrue(all('line' not in c for c in public['choices']))
        self.assertTrue(all(c == {'hint': False, 'kind': 'slot'} for c in public['lines'][0]['choices']))
        canonical = student_questions(self.quiz, released=True)[0]
        expected = [c['id'] for c in canonical['choices']]
        # Guessing the old positional IDs cannot submit a solution.
        self.assertEqual(self.submit({'questions': [{'type': 'cba', 'tokenIds': [expected]}]}).status_code, 400)
        wire = [token_id(self.quiz, 0, original_id) for original_id in expected]
        self.assertEqual(self.submit({'questions': [{'type': 'cba', 'tokenIds': [wire]}]}).status_code, 200)
        saved = QuizSubmission.objects.get(user=self.user, episode=self.quiz)
        self.assertEqual(json.loads(saved.answers)['questions'][0]['tokenIds'], [expected])

    def test_inline_upload_rejects_svg_and_disguised_html(self):
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            for name, body, content_type in (
                ('image.svg', b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>', 'image/svg+xml'),
                ('image.html', b'<html>hello</html>', 'image/png'),
            ):
                response = self.client.post(reverse('progress:vditor_upload'), {
                    'file[]': SimpleUploadedFile(name, body, content_type),
                })
                self.assertNotEqual(response.json()['code'], 0)
            self.assertEqual(list(Path(media).rglob('*')), [])

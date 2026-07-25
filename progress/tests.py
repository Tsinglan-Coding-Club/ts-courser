import json

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from courses.models import Course, Episode, Section
from progress.models import (
    CodeSubmission,
    CourseEnrollment,
    EpisodeReadStatus,
    QuizSubmission,
    UserProgress,
)


class ProgressAccessAndSubmissionTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='teacher',
            email='teacher@example.com',
            password='password',
            role='teacher',
            is_verified_teacher=True,
        )
        self.student = User.objects.create_user(
            username='student',
            email='student@example.com',
            password='password',
        )
        self.outsider = User.objects.create_user(
            username='outsider',
            email='outsider@example.com',
            password='password',
        )
        self.course = Course.objects.create(
            title='Course',
            description='Description',
            creator=self.teacher,
            is_published=True,
            auto_release_results=True,
        )
        self.section = Section.objects.create(course=self.course, title='Section')
        self.material = Episode.objects.create(
            section=self.section, title='Material', type='material'
        )
        self.code_episode = Episode.objects.create(
            section=self.section, title='Code', type='code'
        )
        self.quiz_episode = Episode.objects.create(
            section=self.section, title='Quiz', type='quiz'
        )
        CourseEnrollment.objects.create(user=self.student, course=self.course)

    def test_progress_endpoints_require_course_access(self):
        self.client.force_login(self.outsider)

        response = self.client.post(
            reverse('progress:update_progress'), {'episode_id': self.material.id}
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(UserProgress.objects.filter(user=self.outsider).exists())

        self.client.force_login(self.student)
        response = self.client.post(
            reverse('progress:mark_episode'),
            {'episode_id': self.material.id, 'is_read': 'true'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            EpisodeReadStatus.objects.get(
                user=self.student, episode=self.material
            ).is_read
        )

    def test_upload_stores_draft_without_creating_teacher_visible_submission(self):
        self.client.force_login(self.student)

        response = self.client.post(
            reverse('progress:upload_code'),
            {'episode_id': self.code_episode.id, 'code': 'print("draft")'},
        )

        self.assertEqual(response.status_code, 200)
        upload = CodeSubmission.objects.get(
            user=self.student, episode=self.code_episode
        )
        self.assertEqual(upload.code, 'print("draft")')
        self.assertFalse(upload.is_submitted)
        self.assertIsNone(upload.submitted_at)
        self.assertFalse(
            EpisodeReadStatus.objects.filter(
                user=self.student, episode=self.code_episode
            ).exists()
        )

    def test_formal_submission_promotes_uploaded_code(self):
        self.client.force_login(self.student)
        self.client.post(
            reverse('progress:upload_code'),
            {'episode_id': self.code_episode.id, 'code': 'print("draft")'},
        )

        response = self.client.post(
            reverse('progress:submit_code'),
            {
                'episode_id': self.code_episode.id,
                'code': 'print("final")',
                'test_results': json.dumps([{'passed': True}]),
            },
        )

        self.assertEqual(response.status_code, 200)
        submission = CodeSubmission.objects.get(
            user=self.student, episode=self.code_episode
        )
        self.assertEqual(submission.code, 'print("final")')
        self.assertTrue(submission.is_submitted)
        self.assertIsNotNone(submission.submitted_at)
        self.assertTrue(
            EpisodeReadStatus.objects.get(
                user=self.student, episode=self.code_episode
            ).is_read
        )

    def test_inherited_release_policy_uses_course_default_except_for_frq(self):
        self.client.force_login(self.student)
        mcq_answers = {'questions': [{'type': 'mcq', 'selectedIndex': 0}]}
        response = self.client.post(
            reverse('progress:submit_quiz'),
            {'episode_id': self.quiz_episode.id, 'answers': json.dumps(mcq_answers)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(
            QuizSubmission.objects.get(
                user=self.student, episode=self.quiz_episode
            ).released_at
        )

        QuizSubmission.objects.filter(
            user=self.student, episode=self.quiz_episode
        ).delete()
        self.quiz_episode.quiz_release_policy = 'manual'
        self.quiz_episode.save()
        response = self.client.post(
            reverse('progress:submit_quiz'),
            {
                'episode_id': self.quiz_episode.id,
                'answers': json.dumps({'questions': [{'type': 'frq', 'text': 'Answer'}]}),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(
            QuizSubmission.objects.get(
                user=self.student, episode=self.quiz_episode
            ).released_at
        )

    def test_immediate_episode_policy_releases_frq(self):
        self.quiz_episode.quiz_release_policy = 'immediate'
        self.quiz_episode.save()
        self.client.force_login(self.student)

        response = self.client.post(
            reverse('progress:submit_quiz'),
            {
                'episode_id': self.quiz_episode.id,
                'answers': json.dumps({'questions': [{'type': 'frq', 'text': 'Answer'}]}),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(
            QuizSubmission.objects.get(
                user=self.student, episode=self.quiz_episode
            ).released_at
        )

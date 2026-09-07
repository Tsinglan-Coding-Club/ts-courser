import json
import re

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from courses.models import Course, Episode, Section
from progress.models import CourseEnrollment, QuizSubmission


class LearningBoundaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='student', email='student@test.invalid')
        cls.course = Course.objects.create(
            title='Course', creator=cls.user, is_published=True,
            enrollment_mode='open', enrollment_open=False,
        )
        cls.section = Section.objects.create(title='Section', course=cls.course)
        cls.quiz = Episode.objects.create(
            title='Quiz', section=cls.section, type='quiz', quiz_release_policy='manual',
            info_page_content='## Pick\n>+ Yes\n> No\n\n## Explain\n>= SECRET_REFERENCE_ANSWER',
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse('courses:learning_interface_episode', args=[self.course.pk, self.quiz.pk])

    def test_closed_open_mode_cannot_auto_enroll_but_existing_student_can_learn(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertFalse(CourseEnrollment.objects.filter(user=self.user).exists())
        CourseEnrollment.objects.create(user=self.user, course=self.course)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_open_course_still_auto_enrolls(self):
        self.course.enrollment_open = True
        self.course.save()
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertTrue(CourseEnrollment.objects.filter(user=self.user, course=self.course).exists())

    def test_answers_only_arrive_after_this_students_submission_is_released(self):
        CourseEnrollment.objects.create(user=self.user, course=self.course)
        html = self.client.get(self.url).content.decode()
        self.assertNotIn('SECRET_REFERENCE_ANSWER', html)
        self.assertNotIn('const markdownContent =', html)
        data = json.loads(re.search(r'id="quiz-raw-data" type="application/json">(.*?)</script>', html, re.S)[1])
        self.assertEqual(data[0]['choices'], [{'text': 'Yes'}, {'text': 'No'}])
        self.assertNotIn('refAnswer', data[1])
        submission = QuizSubmission.objects.create(
            user=self.user, episode=self.quiz,
            answers='{"questions":[{"type":"mcq","selectedIndex":0},{"type":"frq","text":"Answer"}]}',
        )
        self.assertNotContains(self.client.get(self.url), 'SECRET_REFERENCE_ANSWER')
        submission.released_at = timezone.now()
        submission.save()
        self.assertContains(self.client.get(self.url), 'SECRET_REFERENCE_ANSWER')

    def test_open_code_mode_course_still_requires_enrollment(self):
        self.course.enrollment_mode = 'code'
        self.course.enrollment_open = True
        self.course.save()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertFalse(CourseEnrollment.objects.filter(user=self.user).exists())

    def test_legacy_invalid_released_answers_render_as_unanswered(self):
        CourseEnrollment.objects.create(user=self.user, course=self.course)
        submission = QuizSubmission.objects.create(
            user=self.user, episode=self.quiz, released_at=timezone.now(),
        )
        for value in ('null', 'broken json', '{"questions":[{"selectedIndex":999},{"text":{}}]}'):
            submission.answers = value
            submission.save()
            response = self.client.get(self.url)
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.context['quiz_answers_json'])
            self.assertEqual(data, {'questions': [{'type': 'mcq'}, {'type': 'frq', 'text': ''}]})

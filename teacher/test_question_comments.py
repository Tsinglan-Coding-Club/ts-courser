"""Per-question feedback follows the submission and its release lifecycle."""
import json

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from courses.models import Course, Episode, Section
from progress.models import CourseEnrollment, QuizSubmission


class QuestionCommentTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='feedback-owner', role='teacher', is_verified_teacher=True,
        )
        self.student = User.objects.create_user(username='feedback-student', role='student')
        self.course = Course.objects.create(title='Feedback', creator=self.teacher, is_published=True)
        self.section = Section.objects.create(course=self.course, title='Unit')
        self.episode = Episode.objects.create(
            section=self.section, title='Quiz', type='quiz',
            info_page_content='## Pick\n>+ Yes\n> No\n\n## Explain\n>= Reference',
            quiz_release_policy='manual',
        )
        CourseEnrollment.objects.create(user=self.student, course=self.course)
        self.answers = {'questions': [
            {'type': 'mcq', 'selectedIndex': 0}, {'type': 'frq', 'text': 'Because'},
        ]}
        self.client.force_login(self.student)
        self.client.post(reverse('progress:submit_quiz'), {
            'episode_id': self.episode.pk, 'answers': json.dumps(self.answers),
        })
        self.submission = QuizSubmission.objects.get(user=self.student, episode=self.episode)
        self.client.force_login(self.teacher)

    def comment(self, index=0, text='Explain your choice.', version=None):
        return self.client.post(reverse('teacher:comment_question'), {
            'submission_id': self.submission.pk,
            'submission_version': version or self.submission.submitted_at.isoformat(),
            'question_index': index, 'comment': text,
        })

    def test_comment_objective_and_frq_edit_clear_and_review(self):
        self.assertEqual(self.comment().status_code, 200)
        self.assertEqual(self.comment(1, 'Useful reasoning.').status_code, 200)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.question_comments, {
            '0': 'Explain your choice.', '1': 'Useful reasoning.',
        })
        response = self.client.get(reverse('teacher:assignment_review', args=[self.course.pk, self.episode.pk]))
        self.assertContains(response, 'Useful reasoning.')
        self.assertEqual(self.comment(0, '').status_code, 200)
        self.submission.refresh_from_db()
        self.assertNotIn('0', self.submission.question_comments)

    def test_invalid_index_length_and_stale_submission_rejected(self):
        for index in (-1, 2, 'bad'):
            self.assertEqual(self.comment(index).status_code, 400)
        self.assertEqual(self.comment(text='a' * 10001).status_code, 400)
        self.assertEqual(self.comment(version='stale').status_code, 409)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.question_comments, {})

    def test_student_and_unassigned_teacher_cannot_comment(self):
        self.client.force_login(self.student)
        self.assertEqual(self.comment().status_code, 403)
        other = User.objects.create_user(username='unassigned', role='teacher', is_verified_teacher=True)
        self.client.force_login(other)
        self.assertEqual(self.comment().status_code, 403)

    def test_feedback_only_projected_after_release_and_safely_encoded(self):
        text = '<script>alert("feedback")</script>'
        self.comment(text=text)
        self.client.force_login(self.student)
        url = reverse('courses:learning_interface_episode', args=[self.course.pk, self.episode.pk])
        response = self.client.get(url)
        self.assertNotContains(response, 'alert("feedback")')
        self.assertEqual(response.context['quiz_questions'], [])
        self.submission.released_at = timezone.now()
        self.submission.save(update_fields=['released_at'])
        response = self.client.get(url)
        self.assertEqual(response.context['quiz_questions'][0]['teacherComment'], text)
        self.assertNotContains(response, text)
        self.assertContains(response, r'\u003Cscript\u003E')

    def test_identical_answers_keep_feedback_changed_answers_clear_it(self):
        self.comment()
        self.client.force_login(self.student)
        url = reverse('progress:submit_quiz')
        self.client.post(url, {'episode_id': self.episode.pk, 'answers': json.dumps(self.answers)})
        self.submission.refresh_from_db()
        self.assertIn('0', self.submission.question_comments)
        self.answers['questions'][0]['selectedIndex'] = 1
        self.client.post(url, {'episode_id': self.episode.pk, 'answers': json.dumps(self.answers)})
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.question_comments, {})

    def test_course_roles_control_all_review_mutations(self):
        from courses.models import CourseTeacherMembership
        collaborator = User.objects.create_user(
            username='feedback-collaborator', role='teacher', is_verified_teacher=True,
        )
        membership = CourseTeacherMembership.objects.create(
            course=self.course, user=collaborator, role=CourseTeacherMembership.VIEW,
        )
        self.client.force_login(collaborator)
        payload = {
            'submission_id': self.submission.pk,
            'submission_version': self.submission.submitted_at.isoformat(),
            'question_index': 1, 'is_correct': 'true', 'comment': 'Feedback',
        }
        for endpoint in ('comment_question', 'grade_frq', 'release_submission', 'cancel_release', 'reset_submission'):
            with self.subTest(endpoint=endpoint):
                response = self.client.post(reverse('teacher:' + endpoint), payload)
                self.assertEqual(response.status_code, 403)
        response = self.client.get(reverse('teacher:assignment_review', args=[self.course.pk, self.episode.pk]))
        self.assertNotContains(response, 'class="btn btn-sm btn-outline-primary mt-2 save-comment-btn"')
        self.assertNotContains(response, 'data-is-correct="true"')
        self.assertNotContains(response, 'data-submission-id="%s"' % self.submission.pk)
        for role in (CourseTeacherMembership.EDIT, CourseTeacherMembership.MANAGE):
            membership.role = role
            membership.save(update_fields=['role'])
            self.assertEqual(self.comment().status_code, 200)
        membership.delete()
        self.assertEqual(self.comment().status_code, 403)

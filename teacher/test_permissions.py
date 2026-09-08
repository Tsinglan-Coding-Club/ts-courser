from importlib import import_module

from django.apps import apps
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from courses.models import Course, CourseTeacherMembership, Episode, Section
from progress.models import CourseEnrollment, QuizSubmission


class CourseTeacherPermissionTests(TestCase):
    def setUp(self):
        self.creator = self._teacher('creator')
        self.viewer = self._teacher('viewer')
        self.editor = self._teacher('editor')
        self.manager = self._teacher('manager')
        self.stranger = self._teacher('stranger')
        self.student = User.objects.create_user(username='student', password='password')
        self.course = Course.objects.create(
            title='Private course', description='Description', creator=self.creator,
            is_published=True,
        )
        self.section = Section.objects.create(course=self.course, title='Section')
        self.episode = Episode.objects.create(
            section=self.section, title='Quiz', type='quiz',
            info_page_content='## Explain\n>= expected answer',
        )
        CourseEnrollment.objects.create(course=self.course, user=self.student)
        self.submission = QuizSubmission.objects.create(
            user=self.student, episode=self.episode, answers='{"questions": [{}]}',
        )
        CourseTeacherMembership.objects.create(
            course=self.course, user=self.viewer, role=CourseTeacherMembership.VIEW,
        )
        CourseTeacherMembership.objects.create(
            course=self.course, user=self.editor, role=CourseTeacherMembership.EDIT,
        )
        CourseTeacherMembership.objects.create(
            course=self.course, user=self.manager, role=CourseTeacherMembership.MANAGE,
        )

    def _teacher(self, username):
        return User.objects.create_user(
            username=username, password='password', role='teacher',
            is_verified_teacher=True,
        )

    def test_course_creator_receives_manager_membership(self):
        self.assertTrue(CourseTeacherMembership.objects.filter(
            course=self.course, user=self.creator,
            role=CourseTeacherMembership.MANAGE,
        ).exists())

    def test_migration_backfills_missing_creator_manager_membership(self):
        CourseTeacherMembership.objects.filter(
            course=self.course, user=self.creator
        ).delete()
        migration = import_module('courses.migrations.0013_courseteachermembership')
        migration.add_creator_manager_memberships(apps, None)
        self.assertTrue(CourseTeacherMembership.objects.filter(
            course=self.course, user=self.creator,
            role=CourseTeacherMembership.MANAGE,
        ).exists())

    def test_viewer_can_see_student_work_but_cannot_edit_or_grade(self):
        self.client.force_login(self.viewer)
        manage = self.client.get(reverse('teacher:course_manage', args=[self.course.id]))
        review = self.client.get(reverse(
            'teacher:assignment_review', args=[self.course.id, self.episode.id]
        ))
        create = self.client.post(reverse('teacher:section_create'), {
            'course_id': self.course.id, 'title': 'Blocked',
        })
        grade = self.client.post(reverse('teacher:grade_frq'), {
            'submission_id': self.submission.id,
            'question_index': '0', 'is_correct': 'true',
            'submission_version': self.submission.submitted_at.isoformat(),
        })
        self.assertEqual(manage.status_code, 200)
        self.assertEqual(review.status_code, 200)
        self.assertContains(review, self.student.username)
        self.assertEqual(create.status_code, 403)
        self.assertEqual(grade.status_code, 403)

    def test_editor_can_create_content_but_cannot_change_teacher_access(self):
        self.client.force_login(self.editor)
        create = self.client.post(reverse('teacher:section_create'), {
            'course_id': self.course.id, 'title': 'Editor section',
        })
        members = self.client.post(reverse('teacher:course_member_save', args=[self.course.id]), {
            'username': self.stranger.username, 'role': CourseTeacherMembership.VIEW,
        })
        self.assertEqual(create.status_code, 302)
        self.assertTrue(Section.objects.filter(course=self.course, title='Editor section').exists())
        self.assertEqual(members.status_code, 403)
        self.assertFalse(CourseTeacherMembership.objects.filter(
            course=self.course, user=self.stranger
        ).exists())

    def test_manager_can_replace_creator_and_course_keeps_a_manager(self):
        creator_membership = CourseTeacherMembership.objects.get(
            course=self.course, user=self.creator,
        )
        self.client.force_login(self.manager)
        response = self.client.post(reverse('teacher:course_member_save', args=[self.course.id]), {
            'username': self.creator.username, 'role': CourseTeacherMembership.VIEW,
        })
        self.assertEqual(response.status_code, 302)
        creator_membership.refresh_from_db()
        self.assertEqual(creator_membership.role, CourseTeacherMembership.VIEW)
        self.assertEqual(self.course.creator, self.creator)

        manager_membership = CourseTeacherMembership.objects.get(
            course=self.course, user=self.manager,
        )
        self.client.post(reverse(
            'teacher:course_member_remove', args=[self.course.id, manager_membership.id]
        ))
        self.assertTrue(CourseTeacherMembership.objects.filter(
            pk=manager_membership.pk
        ).exists())

    def test_unassigned_teacher_cannot_use_learning_or_submission_apis(self):
        self.client.force_login(self.stranger)
        learn = self.client.get(reverse(
            'courses:learning_interface_episode', args=[self.course.id, self.episode.id]
        ))
        submit = self.client.post(reverse('progress:submit_quiz'), {
            'episode_id': self.episode.id, 'answers': '{"questions": [{}]}',
        })
        self.assertEqual(learn.status_code, 302)
        self.assertEqual(submit.status_code, 403)

    def test_membership_stops_working_when_teacher_verification_is_revoked(self):
        self.viewer.is_verified_teacher = False
        self.viewer.save(update_fields=['is_verified_teacher'])
        self.client.force_login(self.viewer)
        manage = self.client.get(reverse('teacher:course_manage', args=[self.course.id]))
        submit = self.client.post(reverse('progress:submit_quiz'), {
            'episode_id': self.episode.id, 'answers': '{"questions": [{}]}',
        })
        # AccountStateMiddleware sends a revoked teacher to its pending page
        # before the teacher decorator runs; either way it cannot view the work.
        self.assertEqual(manage.status_code, 302)
        self.assertEqual(submit.status_code, 403)

    def test_teacher_course_list_only_includes_assigned_courses(self):
        self.client.force_login(self.stranger)
        response = self.client.get(reverse('teacher:course_list'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.course.title)

    def test_course_list_shows_creator_display_name(self):
        self.creator.username = 'entra_123456789'
        self.creator.display_name = 'Course Creator'
        self.creator.save(update_fields=['username', 'display_name'])
        self.client.force_login(self.viewer)

        response = self.client.get(reverse('teacher:course_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-creator="Course Creator"')
        self.assertContains(response, '>Course Creator</td>')
        self.assertNotContains(response, self.creator.username)

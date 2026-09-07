import json

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from courses.models import Course, Episode, Section
from progress.models import CodeSubmission, CodeSubmissionHistory, CourseEnrollment


class CodeSubmissionHistoryTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='history-teacher', password='password', role='teacher',
            is_verified_teacher=True,
        )
        self.student = User.objects.create_user(
            username='history-student', password='password',
        )
        self.other_student = User.objects.create_user(
            username='history-other', password='password',
        )
        self.course = Course.objects.create(
            title='History course', description='Description', creator=self.teacher,
            is_published=True,
        )
        self.episode = Episode.objects.create(
            section=Section.objects.create(course=self.course, title='Section'),
            title='Code', type='code', code_oj_enabled=True,
        )
        CourseEnrollment.objects.create(user=self.student, course=self.course)
        CourseEnrollment.objects.create(user=self.other_student, course=self.course)

    def submit(self, code, results=None):
        return self.client.post(reverse('progress:submit_code'), {
            'episode_id': self.episode.id,
            'code': code,
            'test_results': json.dumps(results if results is not None else [{'passed': True}]),
        })

    def test_every_formal_submission_creates_an_immutable_snapshot(self):
        self.client.force_login(self.student)
        first = self.submit('print("first")')
        second = self.submit('print("second")', [{'passed': False, 'actual': 'x'}])

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        snapshots = list(CodeSubmissionHistory.objects.filter(
            user=self.student, episode=self.episode
        ).order_by('id'))
        self.assertEqual([snapshot.code for snapshot in snapshots], [
            'print("first")', 'print("second")',
        ])
        self.assertEqual(json.loads(snapshots[1].test_results)[0]['actual'], 'x')

    def test_identical_formal_submissions_still_create_distinct_snapshots(self):
        self.client.force_login(self.student)
        self.submit('print("same")')
        self.submit('print("same")')

        self.assertEqual(CodeSubmissionHistory.objects.filter(
            user=self.student, episode=self.episode
        ).count(), 2)

    def test_upload_never_creates_snapshot_or_removes_existing_history(self):
        self.client.force_login(self.student)
        self.submit('print("formal")')
        response = self.client.post(reverse('progress:upload_code'), {
            'episode_id': self.episode.id, 'code': 'print("draft")',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(CodeSubmissionHistory.objects.filter(
            user=self.student, episode=self.episode
        ).count(), 1)
        submission = CodeSubmission.objects.get(user=self.student, episode=self.episode)
        self.assertEqual(submission.code, 'print("draft")')
        self.assertFalse(submission.is_submitted)

    def test_restore_returns_own_snapshot_without_writing_draft_or_history(self):
        self.client.force_login(self.student)
        self.submit('print("formal")')
        snapshot = CodeSubmissionHistory.objects.get(
            user=self.student, episode=self.episode
        )
        self.client.post(reverse('progress:upload_code'), {
            'episode_id': self.episode.id, 'code': 'print("current draft")',
        })

        response = self.client.post(
            reverse('progress:restore_code_history', args=[snapshot.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['code'], 'print("formal")')
        self.assertEqual(CodeSubmissionHistory.objects.filter(
            user=self.student, episode=self.episode
        ).count(), 1)
        self.assertEqual(
            CodeSubmission.objects.get(user=self.student, episode=self.episode).code,
            'print("current draft")',
        )

    def test_history_and_restore_reject_another_students_snapshot(self):
        self.client.force_login(self.student)
        self.submit('print("private")')
        snapshot = CodeSubmissionHistory.objects.get(user=self.student)
        self.client.force_login(self.other_student)

        response = self.client.post(
            reverse('progress:restore_code_history', args=[snapshot.id])
        )

        self.assertEqual(response.status_code, 404)

    def test_history_lists_only_the_current_students_snapshots(self):
        self.client.force_login(self.student)
        self.submit('print("mine")')
        self.client.force_login(self.other_student)
        self.submit('print("theirs")')
        self.client.force_login(self.student)

        response = self.client.get(
            reverse('progress:code_history'), {'episode_id': self.episode.id}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([entry['code'] for entry in response.json()['history']], [
            'print("mine")'
        ])

    def test_teacher_reviews_history_after_later_upload_clears_latest_submission(self):
        self.client.force_login(self.student)
        self.submit('print("submitted")')
        self.client.post(reverse('progress:upload_code'), {
            'episode_id': self.episode.id, 'code': 'print("later draft")',
        })
        snapshot = CodeSubmissionHistory.objects.get(user=self.student)

        self.client.force_login(self.teacher)
        response = self.client.get(
            reverse('teacher:assignment_review', args=[self.course.id, self.episode.id]),
            {'user_id': self.student.id, 'history_id': snapshot.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_submission'], snapshot)
        self.assertContains(response, 'print(&quot;submitted&quot;)')

    def test_teacher_can_review_history_after_student_is_unenrolled(self):
        self.client.force_login(self.student)
        self.submit('print("submitted")')
        CourseEnrollment.objects.filter(
            user=self.student, course=self.course
        ).delete()

        self.client.force_login(self.teacher)
        response = self.client.get(
            reverse('teacher:assignment_review', args=[self.course.id, self.episode.id]),
            {'user_id': self.student.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_submission'].user, self.student)


class CodeSubmissionHistoryMigrationTests(TransactionTestCase):
    """Verify the data migration preserves existing formal submissions only."""
    migrate_from = ('progress', '0006_alter_codesubmission_options')
    migrate_to = ('progress', '0007_codesubmissionhistory')

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])
        old_apps = self.executor.loader.project_state([self.migrate_from]).apps
        CodeSubmission = old_apps.get_model('progress', 'CodeSubmission')
        teacher = User.objects.create_user(
            username='migration-teacher', password='password', role='teacher',
            is_verified_teacher=True,
        )
        student = User.objects.create_user(
            username='migration-student', password='password',
        )
        course = Course.objects.create(
            title='Migration course', description='Description', creator_id=teacher.id,
        )
        episode = Episode.objects.create(
            section=Section.objects.create(course=course, title='Section'),
            title='Code', type='code',
        )
        self.formal = CodeSubmission.objects.create(
            user_id=student.id, episode_id=episode.id, code='print("formal")',
            test_results='[{"passed": true}]', is_submitted=True,
            submitted_at=timezone.now(),
        )
        CodeSubmission.objects.create(
            user_id=teacher.id, episode_id=episode.id, code='print("draft")',
            is_submitted=False,
        )
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_to])

    def tearDown(self):
        self.executor = MigrationExecutor(connection)
        self.executor.migrate(self.executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_backfill_copies_formal_submission_and_preserves_its_timestamp(self):
        apps = self.executor.loader.project_state([self.migrate_to]).apps
        CodeSubmissionHistory = apps.get_model('progress', 'CodeSubmissionHistory')

        snapshots = list(CodeSubmissionHistory.objects.order_by('id'))

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].code, 'print("formal")')
        self.assertEqual(snapshots[0].test_results, '[{"passed": true}]')
        self.assertEqual(snapshots[0].submitted_at, self.formal.submitted_at)

from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import User
from .services import student_username_from_name


class StudentUsernameTests(SimpleTestCase):
    def test_names_become_lowercase_usernames_without_spaces_or_punctuation(self):
        for name, username in (
            ('Abby Ai', 'abbyai'),
            ('  BOB   Li  ', 'bobli'),
            ('Anne-Marie O’Neil', 'annemarieoneil'),
            ('José Muñoz', 'josemunoz'),
            ('Ａｂｂｙ Ａｉ', 'abbyai'),
            ('Class 3 Abby', 'class3abby'),
        ):
            with self.subTest(name=name):
                self.assertEqual(student_username_from_name(name), username)

    def test_names_without_latin_letters_or_digits_require_a_usable_name(self):
        for name in ('---', '学生甲', '   '):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                student_username_from_name(name)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class BulkStudentFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username='platform-admin', password='AdminPassword!234',
            role='admin', local_login_enabled=True, is_staff=False,
        )

    def setUp(self):
        self.client.force_login(self.admin)
        self.url = reverse('accounts:create_local_students')

    def roster(self, names=None, **extra):
        names = ['Abby Ai', 'Bob Li'] if names is None else names
        return {
            'students-TOTAL_FORMS': str(len(names)),
            'students-INITIAL_FORMS': '0',
            **{f'students-{i}-display_name': name for i, name in enumerate(names)},
            **extra,
        }

    def preview(self, names=None):
        return self.client.post(self.url, self.roster(names, action='preview'))

    def create(self, preview, names=None, **extra):
        return self.client.post(self.url, self.roster(
            names, action='create',
            preview_token=preview.context['preview_token'],
            initial_password='123456', **extra,
        ))

    def test_management_links_to_table_with_add_and_paste_support(self):
        management = self.client.get(reverse('accounts:account_management'))
        self.assertContains(management, self.url)
        response = self.client.get(self.url)
        self.assertContains(response, 'name="students-0-display_name"')
        self.assertContains(response, 'bulk-students.js')
        self.assertNotContains(response, 'id="create-students"')

    def test_preview_allocates_names_without_creating_accounts_or_needing_password(self):
        User.objects.create_user(username='ABBYAI')
        response = self.preview([' Abby  Ai ', 'Abby-Ai', '', 'José Muñoz'])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['students'], [
            {'display_name': 'Abby Ai', 'username': 'abbyai2'},
            {'display_name': 'Abby-Ai', 'username': 'abbyai3'},
            {'display_name': 'José Muñoz', 'username': 'josemunoz'},
        ])
        self.assertEqual(User.objects.count(), 2)
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertContains(response, 'Shared initial password')

    def test_batch_uses_shared_password_with_individual_hashes_and_student_roles(self):
        response = self.create(self.preview(), role='admin', is_staff='1')

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/local_students_created.html')
        self.assertIn('no-store', response.headers['Cache-Control'])
        users = list(User.objects.filter(created_by=self.admin).order_by('id'))
        self.assertEqual([user.username for user in users], ['abbyai', 'bobli'])
        self.assertEqual([user.display_name for user in users], ['Abby Ai', 'Bob Li'])
        self.assertNotEqual(users[0].password, users[1].password)
        for user in users:
            self.assertTrue(user.check_password('123456'))
            self.assertTrue(user.local_login_enabled)
            self.assertTrue(user.must_change_credentials)
            self.assertFalse(user.is_staff)
            self.assertFalse(user.is_superuser)
            self.assertEqual(user.role, 'student')
            self.assertEqual(user.email, '')
            self.assertGreater(user.initial_password_expires_at, timezone.now())

    def test_long_expanding_names_can_still_receive_unique_numeric_suffixes(self):
        name = 'ß' * 100
        User.objects.create_user(username='s' * 100)
        User.objects.create_user(username='s' * 100 + '2')
        preview = self.preview([name, name])
        self.assertEqual(
            [student['username'] for student in preview.context['students']],
            ['s' * 100 + '3', 's' * 100 + '4'],
        )

    def test_missing_password_keeps_preview_and_creates_nothing(self):
        preview = self.preview()
        response = self.client.post(self.url, self.roster(
            action='create', preview_token=preview.context['preview_token'],
        ))
        self.assertFormError(
            response.context['password_form'], 'initial_password', 'This field is required.',
        )
        self.assertEqual(response.context['preview_token'], preview.context['preview_token'])
        self.assertEqual(User.objects.count(), 1)

    def test_empty_invalid_and_oversized_rosters_do_not_produce_a_preview(self):
        for names in ([], [' ', ''], ['Abby Ai', '!!!'], ['A' * 101], ['Abby Ai'] * 201):
            with self.subTest(count=len(names)):
                response = self.preview(names)
                self.assertFalse(response.context['formset'].is_valid())
                self.assertFalse(response.context['preview_token'])
                self.assertEqual(User.objects.count(), 1)

    def test_creation_requires_an_unchanged_unexpired_preview_owned_by_admin(self):
        preview = self.preview()
        token = preview.context['preview_token']
        attempts = (
            self.roster(action='create', initial_password='123456'),
            self.roster(action='create', preview_token=token + 'tampered', initial_password='123456'),
            self.roster(['Changed Name', 'Bob Li'], action='create', preview_token=token, initial_password='123456'),
        )
        for payload in attempts:
            with self.subTest(payload=payload['students-0-display_name']):
                response = self.client.post(self.url, payload)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(User.objects.count(), 1)

        with patch('django.core.signing.time.time', return_value=timezone.now().timestamp() + 601):
            expired = self.create(preview)
        self.assertEqual(expired.status_code, 400)

        other_admin = User.objects.create_user(username='other-admin', role='admin')
        self.client.force_login(other_admin)
        foreign = self.create(preview)
        self.assertEqual(foreign.status_code, 400)
        self.assertFalse(User.objects.filter(username='abbyai').exists())

    def test_conflict_after_preview_requires_reviewing_new_usernames(self):
        preview = self.preview()
        User.objects.create_user(username='BOBLI')
        response = self.create(preview)

        self.assertEqual(response.status_code, 409)
        self.assertFalse(User.objects.filter(username='abbyai').exists())
        self.assertEqual(User.objects.count(), 2)
        self.assertFalse(response.context['preview_token'])
        refreshed = self.preview()
        self.assertEqual(refreshed.context['students'][1]['username'], 'bobli2')

    def test_database_conflict_rolls_back_students_created_earlier_in_batch(self):
        preview = self.preview()
        create_user = User.objects.create_user
        calls = 0

        def fail_second_student(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise IntegrityError('Concurrent username conflict')
            return create_user(**kwargs)

        with patch('accounts.services.User.objects.create_user', side_effect=fail_second_student):
            response = self.create(preview)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(calls, 2)
        self.assertEqual(User.objects.count(), 1)

    def test_repeated_submission_does_not_duplicate_or_reset_accounts(self):
        preview = self.preview()
        self.create(preview)
        student = User.objects.get(username='abbyai')
        student.set_password('UpdatedPassword!234')
        student.save(update_fields=('password',))

        response = self.create(preview)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(User.objects.count(), 3)
        student.refresh_from_db()
        self.assertTrue(student.check_password('UpdatedPassword!234'))

    def test_batch_student_must_change_password_and_keep_generated_username(self):
        self.create(self.preview())
        self.client.logout()
        response = self.client.post(reverse('accounts:login'), {
            'username': 'abbyai', 'password': '123456',
        })
        self.assertRedirects(response, reverse('accounts:first_login_credentials'))
        self.assertNotIn('_auth_user_id', self.client.session)
        response = self.client.post(reverse('accounts:first_login_credentials'), {
            'password1': 'NewClassroomPassword!234', 'password2': 'NewClassroomPassword!234',
        })
        self.assertEqual(response.status_code, 302)
        student = User.objects.get(username='abbyai')
        self.assertTrue(student.check_password('NewClassroomPassword!234'))
        self.assertFalse(student.must_change_credentials)
        self.assertEqual(self.client.session['_auth_user_id'], str(student.pk))

    def test_students_and_teachers_cannot_preview_or_create_even_with_staff_flag(self):
        for role in ('student', 'teacher'):
            user = User.objects.create_user(
                username=role, role=role, is_staff=True, is_verified_teacher=True,
            )
            self.client.force_login(user)
            for method in ('get', 'post'):
                with self.subTest(role=role, method=method):
                    response = getattr(self.client, method)(self.url, self.roster(action='preview'))
                    self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username='abbyai').exists())

    def test_anonymous_and_missing_csrf_requests_cannot_submit(self):
        self.client.logout()
        response = self.preview()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse('accounts:login')))
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        response = csrf_client.post(self.url, self.roster(action='preview'))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(User.objects.count(), 1)

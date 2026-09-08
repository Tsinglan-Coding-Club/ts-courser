import hashlib
import shutil
import tempfile
import time
from unittest.mock import Mock, patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .microsoft import MicrosoftIdentityError, verify_id_token
from .models import ExternalIdentity, User
from courses.models import Course, Episode, Section
from progress.models import CourseEnrollment


class RegistrationClosureTests(TestCase):
    def test_legacy_public_registration_endpoints_are_not_routed(self):
        requests = (
            ('get', '/accounts/register/'),
            ('post', '/accounts/register/'),
            ('post', '/accounts/api/send-verification-code/'),
        )

        for method, path in requests:
            with self.subTest(method=method, path=path):
                response = getattr(self.client, method)(path)

                self.assertEqual(response.status_code, 404)


class ProtectedMediaTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root)
        self.settings_override.enable()
        self.owner = User.objects.create_user(
            username='media-owner', role='teacher', is_verified_teacher=True,
        )
        self.student = User.objects.create_user(username='media-student', role='student')
        self.course = Course.objects.create(
            title='Protected course',
            description='Private files',
            creator=self.owner,
            is_published=True,
        )
        section = Section.objects.create(course=self.course, title='Section')
        self.episode = Episode.objects.create(
            section=section,
            title='PDF lesson',
            type='material',
            content_pdf=SimpleUploadedFile(
                'lesson.pdf',
                b'%PDF-1.4 protected lesson',
                content_type='application/pdf',
            ),
        )

    def tearDown(self):
        self.settings_override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)

    def test_episode_pdf_requires_login_and_course_access(self):
        media_url = self.episode.content_pdf.url
        anonymous_response = self.client.get(media_url)
        self.assertEqual(anonymous_response.status_code, 302)

        self.client.force_login(self.student)
        forbidden_response = self.client.get(media_url)
        self.assertEqual(forbidden_response.status_code, 403)

        CourseEnrollment.objects.create(user=self.student, course=self.course)
        allowed_response = self.client.get(media_url)
        self.assertEqual(allowed_response.status_code, 200)
        self.assertIn(b'protected lesson', b''.join(allowed_response.streaming_content))

    def test_pending_teacher_cannot_bypass_account_gate_with_media_url(self):
        pending_teacher = User.objects.create_user(
            username='pending-media-teacher',
            role='teacher',
            is_verified_teacher=False,
        )
        self.client.force_login(pending_teacher)

        response = self.client.get(self.episode.content_pdf.url)

        self.assertRedirects(
            response,
            reverse('accounts:teacher_pending'),
            fetch_redirect_response=False,
        )


@override_settings(
    MS_ENTRA_TENANT_ID='7222912a-435d-423b-b22b-74b909c3bf8b',
    MS_ENTRA_CLIENT_ID='5910709e-99db-4cc0-9468-88497aa32f23',
)
class MicrosoftTokenVerificationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.other_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def token(self, *, private_key=None, nonce=None, exp_offset=300):
        now = int(time.time())
        tenant_id = '7222912a-435d-423b-b22b-74b909c3bf8b'
        claims = {
            'aud': '5910709e-99db-4cc0-9468-88497aa32f23',
            'exp': now + exp_offset,
            'iat': now,
            'iss': f'https://login.microsoftonline.com/{tenant_id}/v2.0',
            'nbf': now - 1,
            'nonce': nonce or hashlib.sha256(b'raw-flow-nonce').hexdigest(),
            'oid': '11111111-2222-3333-4444-555555555555',
            'sub': 'subject',
            'tid': tenant_id,
        }
        return jwt.encode(
            claims,
            private_key or self.private_key,
            algorithm='RS256',
            headers={'kid': 'test-key'},
        )

    def verify_with_public_key(self, token, flow_nonce='raw-flow-nonce'):
        signing_key = Mock(key=self.private_key.public_key())
        jwk_client = Mock()
        jwk_client.get_signing_key_from_jwt.return_value = signing_key
        with patch('accounts.microsoft._get_jwk_client', return_value=jwk_client):
            return verify_id_token(token, flow_nonce)

    def test_valid_signed_token_is_accepted(self):
        claims = self.verify_with_public_key(self.token())

        self.assertEqual(claims['sub'], 'subject')

    def test_expired_wrong_signature_and_wrong_nonce_are_rejected(self):
        invalid_tokens = (
            self.token(exp_offset=-300),
            self.token(private_key=self.other_private_key),
            self.token(nonce='wrong-nonce'),
        )

        for token in invalid_tokens:
            with self.subTest(token=token[:30]):
                with self.assertRaises(MicrosoftIdentityError):
                    self.verify_with_public_key(token)


class LocalAccountFlowTests(TestCase):
    def setUp(self):
        self.platform_admin = User.objects.create_user(
            username='platform-admin',
            password='AdminPassword!234',
            role='admin',
            local_login_enabled=True,
            is_staff=False,
        )

    def test_platform_admin_can_issue_a_local_student_credential(self):
        self.client.force_login(self.platform_admin)

        response = self.client.post(
            reverse('accounts:create_local_student'),
            {
                'username': 'issued-student',
                'initial_password': '123456',
                'display_name': 'Issued Student',
                'email': 'issued@example.test',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/local_account_created.html')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        issued_student = User.objects.get(username='issued-student')
        initial_password = response.context['initial_password']
        self.assertEqual(initial_password, '123456')
        self.assertEqual(issued_student.role, 'student')
        self.assertEqual(issued_student.created_by, self.platform_admin)
        self.assertTrue(issued_student.local_login_enabled)
        self.assertTrue(issued_student.must_change_credentials)
        self.assertTrue(issued_student.check_password(initial_password))
        self.assertNotEqual(issued_student.password, initial_password)
        self.assertGreater(issued_student.initial_password_expires_at, timezone.now())

    def test_student_creation_requires_administrator_supplied_credentials(self):
        self.client.force_login(self.platform_admin)
        data = {
            'username': 'issued-student',
            'initial_password': '123456',
            'display_name': 'Issued Student',
        }

        for field in ('username', 'initial_password'):
            for value in (None, ''):
                with self.subTest(field=field, value=value):
                    payload = data.copy()
                    if value is None:
                        payload.pop(field)
                    else:
                        payload[field] = value
                    response = self.client.post(
                        reverse('accounts:create_local_student'), payload,
                    )

                    self.assertFormError(
                        response.context['form'], field, 'This field is required.',
                    )
                    self.assertEqual(User.objects.count(), 1)

    def test_student_creation_rejects_invalid_or_duplicate_usernames(self):
        self.client.force_login(self.platform_admin)

        for username in ('name with spaces', 'PLATFORM-ADMIN'):
            with self.subTest(username=username):
                response = self.client.post(
                    reverse('accounts:create_local_student'),
                    {
                        'username': username,
                        'initial_password': '123456',
                        'display_name': 'Issued Student',
                    },
                )

                self.assertIn('username', response.context['form'].errors)
                self.assertEqual(User.objects.count(), 1)
                self.assertNotContains(response, 'value="123456"')

    def test_student_creation_preserves_password_whitespace_and_optional_email(self):
        self.client.force_login(self.platform_admin)
        password = '  classroom password  '

        response = self.client.post(
            reverse('accounts:create_local_student'),
            {
                'username': 'issued-student',
                'initial_password': password,
                'display_name': 'Issued Student',
            },
        )

        self.assertTemplateUsed(response, 'accounts/local_account_created.html')
        student = User.objects.get(username='issued-student')
        self.assertTrue(student.check_password(password))
        self.assertEqual(student.email, '')

    def test_django_staff_is_not_a_platform_admin(self):
        staff_student = User.objects.create_user(
            username='staff-student',
            password='StaffPassword!234',
            role='student',
            local_login_enabled=True,
            is_staff=True,
        )
        self.client.force_login(staff_student)

        management_response = self.client.get(reverse('accounts:account_management'))
        issuance_response = self.client.get(reverse('accounts:create_local_student'))

        self.assertEqual(management_response.status_code, 403)
        self.assertEqual(issuance_response.status_code, 403)
        self.assertFalse(staff_student.is_admin)

    def test_platform_admin_role_does_not_require_django_staff_status(self):
        self.client.force_login(self.platform_admin)

        management_response = self.client.get(reverse('accounts:account_management'))
        issuance_response = self.client.get(reverse('accounts:create_local_student'))

        self.assertEqual(management_response.status_code, 200)
        self.assertEqual(issuance_response.status_code, 200)
        self.assertTrue(self.platform_admin.is_admin)
        self.assertFalse(self.platform_admin.is_staff)

    def test_create_superuser_is_a_controlled_platform_admin(self):
        superuser = User.objects.create_superuser(
            username='bootstrap-admin',
            password='BootstrapPassword!234',
        )

        self.assertEqual(superuser.role, 'admin')
        self.assertTrue(superuser.is_staff)
        self.assertTrue(superuser.is_superuser)
        self.assertTrue(superuser.local_login_enabled)
        self.assertFalse(superuser.must_change_credentials)

    def test_superuser_can_open_local_account_add_form_in_django_admin(self):
        superuser = User.objects.create_superuser(
            username='ops-admin',
            password='BootstrapPassword!234',
        )
        self.client.force_login(superuser)

        response = self.client.get(reverse('admin:accounts_user_add'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Role')

    def test_non_superuser_admin_cannot_reset_superuser_password(self):
        bootstrap_admin = User.objects.create_superuser(
            username='protected-superuser',
            password='OriginalPassword!234',
        )
        delegated_admin = User.objects.create_user(
            username='delegated-admin',
            password='DelegatedPassword!234',
            role='admin',
            local_login_enabled=True,
            is_staff=True,
        )
        self.client.force_login(delegated_admin)

        response = self.client.post(
            reverse('admin:auth_user_password_change', args=(bootstrap_admin.pk,)),
            {
                'password1': 'TakenOverPassword!567',
                'password2': 'TakenOverPassword!567',
            },
        )

        self.assertEqual(response.status_code, 403)
        bootstrap_admin.refresh_from_db()
        self.assertTrue(bootstrap_admin.check_password('OriginalPassword!234'))
        self.assertFalse(bootstrap_admin.check_password('TakenOverPassword!567'))


class FirstLoginCredentialTests(TestCase):
    def make_temporary_student(self):
        return User.objects.create_user(
            username='temporary-student',
            password='InitialPassword!234',
            role='student',
            local_login_enabled=True,
            must_change_credentials=True,
            initial_password_expires_at=timezone.now() + timezone.timedelta(days=1),
        )

    def test_first_login_changes_password_and_keeps_issued_student_username(self):
        student = self.make_temporary_student()

        login_response = self.client.post(
            reverse('accounts:login'),
            {
                'username': 'temporary-student',
                'password': 'InitialPassword!234',
                'next': reverse('accounts:profile'),
            },
        )

        self.assertRedirects(
            login_response,
            reverse('accounts:first_login_credentials'),
            fetch_redirect_response=False,
        )
        self.assertNotIn('_auth_user_id', self.client.session)

        setup_response = self.client.get(reverse('accounts:first_login_credentials'))
        self.assertNotContains(setup_response, 'name="username"')
        self.assertContains(setup_response, student.username)

        change_response = self.client.post(
            reverse('accounts:first_login_credentials'),
            {
                'password1': 'NewStudentPassword!567',
                'password2': 'NewStudentPassword!567',
            },
        )

        self.assertRedirects(
            change_response,
            reverse('accounts:profile'),
            fetch_redirect_response=False,
        )
        student.refresh_from_db()
        self.assertEqual(student.username, 'temporary-student')
        self.assertTrue(student.check_password('NewStudentPassword!567'))
        self.assertFalse(student.check_password('InitialPassword!234'))
        self.assertFalse(student.must_change_credentials)
        self.assertIsNone(student.initial_password_expires_at)
        self.assertIsNotNone(student.password_changed_at)
        self.assertEqual(self.client.session['_auth_user_id'], str(student.pk))

        self.client.logout()
        returning_response = self.client.post(
            reverse('accounts:login'),
            {'username': student.username, 'password': 'NewStudentPassword!567'},
        )
        self.assertRedirects(
            returning_response,
            reverse('courses:course_list'),
            fetch_redirect_response=False,
        )
        self.assertEqual(self.client.session['_auth_user_id'], str(student.pk))

    def test_first_login_rejects_retaining_initial_password(self):
        student = self.make_temporary_student()
        self.client.post(
            reverse('accounts:login'),
            {
                'username': 'temporary-student',
                'password': 'InitialPassword!234',
            },
        )

        same_password_response = self.client.post(
            reverse('accounts:first_login_credentials'),
            {
                'password1': 'InitialPassword!234',
                'password2': 'InitialPassword!234',
            },
        )
        self.assertEqual(same_password_response.status_code, 200)
        self.assertFormError(
            same_password_response.context['form'],
            'password1',
            'The new password must differ from the initial password.',
        )
        student.refresh_from_db()
        self.assertEqual(student.username, 'temporary-student')
        self.assertTrue(student.must_change_credentials)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_first_login_ignores_submitted_student_username(self):
        student = self.make_temporary_student()
        self.client.post(
            reverse('accounts:login'),
            {'username': student.username, 'password': 'InitialPassword!234'},
        )

        response = self.client.post(
            reverse('accounts:first_login_credentials'),
            {
                'username': 'student-chosen-name',
                'password1': 'NewStudentPassword!567',
                'password2': 'NewStudentPassword!567',
            },
        )

        self.assertRedirects(
            response, reverse('courses:course_list'), fetch_redirect_response=False,
        )
        student.refresh_from_db()
        self.assertEqual(student.username, 'temporary-student')
        self.assertTrue(student.check_password('NewStudentPassword!567'))

    def test_first_login_still_validates_password_strength_and_confirmation(self):
        student = self.make_temporary_student()
        self.client.post(
            reverse('accounts:login'),
            {'username': student.username, 'password': 'InitialPassword!234'},
        )

        for password1, password2, error_field in (
            ('NewStudentPassword!567', 'DifferentPassword!567', 'password2'),
            ('123456', '123456', 'password1'),
            (student.username, student.username, 'password1'),
        ):
            with self.subTest(error_field=error_field, password=password1):
                response = self.client.post(
                    reverse('accounts:first_login_credentials'),
                    {'password1': password1, 'password2': password2},
                )

                self.assertIn(error_field, response.context['form'].errors)
                student.refresh_from_db()
                self.assertTrue(student.check_password('InitialPassword!234'))
                self.assertTrue(student.must_change_credentials)
                self.assertNotIn('_auth_user_id', self.client.session)

    def test_issued_administrator_still_changes_both_credentials(self):
        administrator = self.make_temporary_student()
        administrator.role = 'admin'
        administrator.save(update_fields=('role',))
        self.client.post(
            reverse('accounts:login'),
            {'username': administrator.username, 'password': 'InitialPassword!234'},
        )

        setup_response = self.client.get(reverse('accounts:first_login_credentials'))
        self.assertContains(setup_response, 'name="username"')

        response = self.client.post(
            reverse('accounts:first_login_credentials'),
            {
                'username': 'permanent-admin',
                'password1': 'NewAdminPassword!567',
                'password2': 'NewAdminPassword!567',
            },
        )

        self.assertRedirects(
            response, reverse('courses:course_list'), fetch_redirect_response=False,
        )
        administrator.refresh_from_db()
        self.assertEqual(administrator.username, 'permanent-admin')
        self.assertTrue(administrator.check_password('NewAdminPassword!567'))

    def test_local_login_rejects_an_external_next_url(self):
        student = User.objects.create_user(
            username='returning-student',
            password='ReturningPassword!234',
            role='student',
            local_login_enabled=True,
        )

        response = self.client.post(
            reverse('accounts:login'),
            {
                'username': student.username,
                'password': 'ReturningPassword!234',
                'next': 'https://attacker.example/steal-session',
            },
        )

        self.assertRedirects(
            response,
            reverse('courses:course_list'),
            fetch_redirect_response=False,
        )

    def test_password_login_rejects_accounts_without_local_login_enabled(self):
        external_only = User.objects.create_user(
            username='external-only',
            password='UnexpectedPassword!234',
            role='student',
            local_login_enabled=False,
        )

        response = self.client.post(
            reverse('accounts:login'),
            {'username': external_only.username, 'password': 'UnexpectedPassword!234'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_expired_initial_password_cannot_start_credential_change(self):
        student = self.make_temporary_student()
        student.initial_password_expires_at = timezone.now() - timezone.timedelta(seconds=1)
        student.save(update_fields=('initial_password_expires_at',))

        response = self.client.post(
            reverse('accounts:login'),
            {'username': student.username, 'password': 'InitialPassword!234'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('credential_change_user_id', self.client.session)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_logout_requires_post_and_clears_auth_and_preauth_sessions(self):
        student = User.objects.create_user(
            username='signed-in-student',
            password='SignedInPassword!234',
            role='student',
            local_login_enabled=True,
        )
        self.client.force_login(student)
        session = self.client.session
        session['credential_change_user_id'] = student.pk
        session['credential_change_password_hash'] = student.password
        session['credential_change_started_at'] = timezone.now().isoformat()
        session['credential_change_next'] = reverse('accounts:profile')
        session.save()

        get_response = self.client.get(reverse('accounts:logout'))

        self.assertEqual(get_response.status_code, 405)
        self.assertIn('_auth_user_id', self.client.session)

        post_response = self.client.post(reverse('accounts:logout'))

        self.assertRedirects(
            post_response,
            reverse('accounts:login'),
            fetch_redirect_response=False,
        )
        for key in (
            '_auth_user_id',
            'credential_change_user_id',
            'credential_change_password_hash',
            'credential_change_started_at',
            'credential_change_next',
        ):
            self.assertNotIn(key, self.client.session)

    def test_existing_session_marked_for_credential_change_can_still_logout(self):
        student = User.objects.create_user(
            username='reset-student',
            password='ResetPassword!234',
            role='student',
            local_login_enabled=True,
        )
        self.client.force_login(student)
        student.must_change_credentials = True
        student.save(update_fields=('must_change_credentials',))

        response = self.client.post(reverse('accounts:logout'))

        self.assertRedirects(
            response,
            reverse('accounts:login'),
            fetch_redirect_response=False,
        )
        self.assertNotIn('_auth_user_id', self.client.session)


@override_settings(
    MS_ENTRA_ENABLED=True,
    MS_ENTRA_TENANT_ID='7222912a-435d-423b-b22b-74b909c3bf8b',
    MS_ENTRA_CLIENT_ID='5910709e-99db-4cc0-9468-88497aa32f23',
    MS_ENTRA_CLIENT_SECRET='test-client-secret',
    MS_ENTRA_REDIRECT_URI='https://courser.tsinglan.top/accounts/microsoft/callback/',
)
class MicrosoftAccountFlowTests(TestCase):
    tenant_id = '7222912a-435d-423b-b22b-74b909c3bf8b'
    client_id = '5910709e-99db-4cc0-9468-88497aa32f23'

    def claims(self, *, object_id, username, name, **overrides):
        claims = {
            'tid': self.tenant_id,
            'oid': object_id,
            'aud': self.client_id,
            'iss': f'https://login.microsoftonline.com/{self.tenant_id}/v2.0',
            'acct': '0',
            'preferred_username': username,
            'name': name,
        }
        claims.update(overrides)
        return claims

    def complete_microsoft_sign_in(
        self,
        *,
        claims,
        role=None,
        next_url=None,
        start_data=None,
    ):
        app = Mock()
        app.initiate_auth_code_flow.return_value = {
            'auth_uri': 'https://login.microsoftonline.test/authorize',
            'state': 'state-value',
            'nonce': 'flow-nonce',
        }
        app.acquire_token_by_auth_code_flow.return_value = {
            'id_token': 'signed-id-token',
        }
        login_data = dict(start_data or {})
        if next_url is not None:
            login_data['next'] = next_url

        with (
            patch('accounts.views.build_msal_app', return_value=app),
            patch('accounts.views.verify_id_token', return_value=claims),
        ):
            start_response = self.client.post(
                reverse('accounts:microsoft_login'),
                login_data,
            )
            callback_response = self.client.get(
                reverse('accounts:microsoft_callback'),
                {'code': 'authorization-code', 'state': 'state-value'},
            )

        self.assertRedirects(
            start_response,
            'https://login.microsoftonline.test/authorize',
            fetch_redirect_response=False,
        )
        if (
            role is not None
            and callback_response.status_code == 302
            and callback_response.url
            == reverse('accounts:microsoft_role_selection')
        ):
            return self.client.post(
                reverse('accounts:microsoft_role_selection'),
                {'role': role},
            )
        return callback_response

    def test_login_page_has_one_microsoft_entry_and_no_role_selector(self):
        response = self.client.get(reverse('accounts:login'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sign in with your school account')
        self.assertContains(response, 'Sign in with username and password')
        self.assertContains(response, 'auth-fluid-background')
        self.assertContains(response, 'vendor/webgl-fluid/webgl-fluid.umd.js')
        self.assertContains(response, 'js/auth-fluid.js')
        self.assertContains(response, '<details class="local-login-panel">')
        self.assertNotContains(response, '<details class="local-login-panel" open>')
        self.assertNotContains(response, 'Welcome back')
        self.assertNotContains(response, 'Teacher access requires')
        self.assertNotContains(response, 'name="role"')

    def test_new_identity_selects_role_only_after_microsoft_verification(self):
        response = self.complete_microsoft_sign_in(
            claims=self.claims(
                object_id='88888888-2222-3333-4444-555555555555',
                username='new.student@tsinglan.org',
                name='New Student',
            ),
        )

        self.assertRedirects(
            response,
            reverse('accounts:microsoft_role_selection'),
            fetch_redirect_response=False,
        )
        self.assertFalse(User.objects.exists())
        self.assertFalse(ExternalIdentity.objects.exists())

        selection_page = self.client.get(
            reverse('accounts:microsoft_role_selection'),
        )
        self.assertContains(selection_page, 'Microsoft school account verified')
        self.assertContains(selection_page, 'new.student@tsinglan.org')
        self.assertContains(selection_page, 'name="role" value="student"')
        self.assertContains(selection_page, 'name="role" value="teacher"')

        selection_response = self.client.post(
            reverse('accounts:microsoft_role_selection'),
            {'role': 'student'},
        )
        self.assertRedirects(
            selection_response,
            reverse('courses:course_list'),
            fetch_redirect_response=False,
        )
        self.assertEqual(User.objects.get().role, 'student')
        self.assertEqual(ExternalIdentity.objects.count(), 1)

    def test_role_selection_requires_a_verified_microsoft_identity(self):
        response = self.client.get(
            reverse('accounts:microsoft_role_selection'),
        )

        self.assertRedirects(
            response,
            reverse('accounts:login'),
            fetch_redirect_response=False,
        )
        self.assertFalse(User.objects.exists())

    def test_student_identity_is_created_once_and_reused(self):
        object_id = '11111111-2222-3333-4444-555555555555'
        first_response = self.complete_microsoft_sign_in(
            role='student',
            claims=self.claims(
                object_id=object_id,
                username='student@tsinglan.org',
                name='Original Name',
            ),
            next_url=reverse('accounts:profile'),
        )

        self.assertRedirects(
            first_response,
            reverse('accounts:profile'),
            fetch_redirect_response=False,
        )
        student = User.objects.get()
        identity = ExternalIdentity.objects.get()
        self.assertEqual(student.role, 'student')
        self.assertEqual(student.display_name, 'Original Name')
        self.assertEqual(student.email, 'student@tsinglan.org')
        self.assertFalse(student.local_login_enabled)
        self.assertFalse(student.has_usable_password())
        self.assertEqual(identity.user, student)
        self.assertEqual(identity.tenant_id, self.tenant_id)
        self.assertEqual(identity.object_id, object_id)

        self.client.post(reverse('accounts:logout'))
        second_response = self.complete_microsoft_sign_in(
            role='student',
            claims=self.claims(
                object_id=object_id,
                username='renamed@tsinglan.org',
                name='Updated Name',
            ),
        )

        self.assertRedirects(
            second_response,
            reverse('courses:course_list'),
            fetch_redirect_response=False,
        )
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(ExternalIdentity.objects.count(), 1)
        student.refresh_from_db()
        identity.refresh_from_db()
        self.assertEqual(student.email, 'renamed@tsinglan.org')
        self.assertEqual(student.display_name, 'Updated Name')
        self.assertEqual(identity.principal_name, 'renamed@tsinglan.org')
        self.assertIsNotNone(identity.last_authenticated_at)

    def test_guest_account_is_allowed_but_wrong_tenant_is_rejected(self):
        guest_response = self.complete_microsoft_sign_in(
            role='student',
            claims=self.claims(
                object_id='22222222-2222-3333-4444-555555555555',
                username='guest_external.example.com#EXT#@tsinglan.onmicrosoft.com',
                name='Guest User',
                acct='1',
            ),
        )

        self.assertRedirects(
            guest_response,
            reverse('courses:course_list'),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            User.objects.get().email,
            'guest_external.example.com#EXT#@tsinglan.onmicrosoft.com',
        )
        self.assertEqual(ExternalIdentity.objects.count(), 1)

        self.client = Client()
        response = self.complete_microsoft_sign_in(
            claims=self.claims(
                object_id='33333333-2222-3333-4444-555555555555',
                username='outsider@tsinglan.org',
                name='Wrong Tenant',
                tid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
            ),
        )

        self.assertEqual(response.status_code, 403)
        self.assertContains(
            response,
            'This Microsoft tenant is not allowed.',
            status_code=403,
        )
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(ExternalIdentity.objects.count(), 1)

    def test_missing_acct_claim_is_allowed_but_wrong_audience_is_rejected(self):
        missing_acct = self.claims(
            object_id='55555555-2222-3333-4444-555555555555',
            username='member@tsinglan.org',
            name='Missing Claim',
        )
        missing_acct.pop('acct')
        wrong_audience = self.claims(
            object_id='66666666-2222-3333-4444-555555555555',
            username='member@tsinglan.org',
            name='Wrong Audience',
            aud='not-this-application',
        )

        missing_acct_response = self.complete_microsoft_sign_in(
            role='student',
            claims=missing_acct,
        )
        self.assertRedirects(
            missing_acct_response,
            reverse('courses:course_list'),
            fetch_redirect_response=False,
        )
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(ExternalIdentity.objects.count(), 1)

        self.client = Client()
        wrong_audience_response = self.complete_microsoft_sign_in(
            claims=wrong_audience,
        )
        self.assertEqual(wrong_audience_response.status_code, 403)

        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(ExternalIdentity.objects.count(), 1)

    def test_login_page_role_input_cannot_change_existing_identity(self):
        object_id = '77777777-2222-3333-4444-555555555555'
        claims = self.claims(
            object_id=object_id,
            username='student@tsinglan.org',
            name='Student',
        )
        self.complete_microsoft_sign_in(role='student', claims=claims)
        self.client.post(reverse('accounts:logout'))

        response = self.complete_microsoft_sign_in(
            role='teacher',
            claims=claims,
            start_data={'role': 'teacher'},
        )

        self.assertRedirects(
            response,
            reverse('courses:course_list'),
            fetch_redirect_response=False,
        )
        user = User.objects.get()
        self.assertEqual(user.role, 'student')
        self.assertFalse(user.is_verified_teacher)

    def test_teacher_is_confined_until_a_platform_admin_approves_them(self):
        teacher_response = self.complete_microsoft_sign_in(
            role='teacher',
            claims=self.claims(
                object_id='44444444-2222-3333-4444-555555555555',
                username='teacher@tsinglan.org',
                name='Pending Teacher',
            ),
        )

        self.assertRedirects(
            teacher_response,
            reverse('accounts:teacher_pending'),
            fetch_redirect_response=False,
        )
        teacher = User.objects.get(username__startswith='entra_')
        self.assertEqual(teacher.role, 'teacher')
        self.assertFalse(teacher.is_verified_teacher)
        blocked_response = self.client.get(reverse('courses:course_list'))
        self.assertRedirects(
            blocked_response,
            reverse('accounts:teacher_pending'),
            fetch_redirect_response=False,
        )
        blocked_api_response = self.client.get(
            '/api/progress/update/',
            HTTP_ACCEPT='application/json',
        )
        self.assertEqual(blocked_api_response.status_code, 403)
        self.assertEqual(blocked_api_response.json()['account_state'], 'teacher_pending')

        self.client.post(reverse('accounts:logout'))
        admin = User.objects.create_user(
            username='approving-admin',
            password='AdminPassword!234',
            role='admin',
            local_login_enabled=True,
            is_staff=False,
        )
        self.client.force_login(admin)
        approval_response = self.client.post(
            reverse('accounts:approve_teacher', args=(teacher.pk,)),
        )

        self.assertRedirects(
            approval_response,
            reverse('accounts:account_management'),
            fetch_redirect_response=False,
        )
        teacher.refresh_from_db()
        self.assertTrue(teacher.is_verified_teacher)
        self.assertEqual(teacher.teacher_reviewed_by, admin)
        self.assertIsNotNone(teacher.teacher_reviewed_at)

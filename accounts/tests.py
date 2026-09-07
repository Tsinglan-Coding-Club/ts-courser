from io import BytesIO
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import User
from ts_courser.utils import ImageUploadValidationError, validate_and_reencode_image


class ImageUploadValidationTests(TestCase):
    def make_image_upload(self, image_format='PNG', name='avatar.any'):
        image_bytes = BytesIO()
        Image.new('RGB', (20, 20), 'blue').save(image_bytes, format=image_format)
        return SimpleUploadedFile(
            name,
            image_bytes.getvalue(),
            content_type='text/html',
        )

    def test_detected_raster_type_controls_safe_name_and_content_type(self):
        upload = self.make_image_upload('PNG', 'dangerous.svg')

        sanitized = validate_and_reencode_image(upload)

        self.assertEqual(sanitized.name, 'dangerous.png')
        self.assertEqual(sanitized.content_type, 'image/png')
        with Image.open(sanitized) as image:
            self.assertEqual(image.format, 'PNG')

    def test_rejects_html_disguised_as_an_image(self):
        upload = SimpleUploadedFile(
            'avatar.png', b'<svg xmlns="http://www.w3.org/2000/svg"></svg>',
            content_type='image/png',
        )

        with self.assertRaises(ImageUploadValidationError):
            validate_and_reencode_image(upload)

    def test_rejects_images_exceeding_pixel_bound(self):
        upload = self.make_image_upload('PNG')

        with self.assertRaises(ImageUploadValidationError):
            validate_and_reencode_image(upload, max_pixels=100)


class ProfileAvatarUploadTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root)
        self.settings_override.enable()
        self.user = User.objects.create_user(
            username='avatar-user', email='avatar@example.com', password='password123'
        )
        self.client.force_login(self.user)

    def tearDown(self):
        self.settings_override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)

    def make_image_upload(self, image_format='PNG', name='avatar.svg'):
        image_bytes = BytesIO()
        Image.new('RGB', (20, 20), 'red').save(image_bytes, format=image_format)
        return SimpleUploadedFile(name, image_bytes.getvalue(), content_type='text/html')

    def test_profile_upload_accepts_real_image_with_untrusted_content_type(self):
        response = self.client.post(
            reverse('accounts:profile_edit'),
            {'display_name': 'Avatar User', 'bio': '', 'avatar': self.make_image_upload()},
        )

        self.assertRedirects(response, reverse('accounts:profile'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.avatar.name.endswith('.png'))
        with Image.open(self.user.avatar.path) as image:
            self.assertEqual(image.format, 'PNG')

    def test_profile_upload_rejects_disguised_html_without_replacing_avatar(self):
        existing_avatar = self.make_image_upload('JPEG', 'existing.jpg')
        self.user.avatar.save('existing.jpg', existing_avatar, save=True)
        original_name = self.user.avatar.name

        response = self.client.post(
            reverse('accounts:profile_edit'),
            {
                'display_name': 'Avatar User',
                'bio': '',
                'avatar': SimpleUploadedFile('avatar.png', b'<html>bad</html>', 'image/png'),
            },
        )

        self.assertRedirects(response, reverse('accounts:profile_edit'))
        self.user.refresh_from_db()
        self.assertEqual(self.user.avatar.name, original_name)

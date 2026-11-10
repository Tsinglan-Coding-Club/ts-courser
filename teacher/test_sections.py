from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from courses.models import Course, CourseTeacherMembership, Episode, Section


class SectionEmojiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = get_user_model().objects.create_user(
            username='section-teacher', role='teacher', is_verified_teacher=True,
        )
        cls.viewer = get_user_model().objects.create_user(
            username='section-viewer', role='teacher', is_verified_teacher=True,
        )
        cls.course = Course.objects.create(
            title='Python', description='Course', creator=cls.teacher,
        )
        CourseTeacherMembership.objects.create(
            course=cls.course, user=cls.viewer, role=CourseTeacherMembership.VIEW,
        )
        cls.section = Section.objects.create(
            course=cls.course, title='Basics', emoji='🐍', order=3,
        )
        cls.episode = Episode.objects.create(
            section=cls.section, title='Quiz', type='quiz',
        )

    def setUp(self):
        self.client.force_login(self.teacher)

    def test_create_section_with_custom_or_blank_emoji(self):
        for emoji in ('👩🏽‍💻', 'devicon:python:original', 'heroicons:24-outline:academic-cap', ''):
            with self.subTest(emoji=emoji):
                response = self.client.post(reverse('teacher:section_create'), {
                    'course_id': self.course.pk, 'title': 'New section',
                    'emoji': emoji,
                })
                self.assertRedirects(response, reverse(
                    'teacher:course_edit', args=[self.course.pk],
                ))
                section = self.course.sections.order_by('-order').first()
                self.assertEqual(section.emoji, emoji)
                self.assertEqual(section.title, 'New section')

    def test_edit_and_clear_emoji_preserve_section_order_and_episodes(self):
        url = reverse('teacher:section_rename', args=[self.section.pk])
        for emoji in ('🚀', 'devicon:python:original', 'heroicons:24-outline:academic-cap', ''):
            with self.subTest(emoji=emoji):
                response = self.client.post(url, {
                    'title': '  Renamed  ', 'emoji': emoji,
                })
                self.assertEqual(response.status_code, 302)
                self.section.refresh_from_db()
                self.assertEqual(self.section.title, 'Renamed')
                self.assertEqual(self.section.emoji, emoji)
                self.assertEqual(self.section.order, 3)
                self.assertEqual(list(self.section.episodes.all()), [self.episode])

    def test_title_only_edit_keeps_existing_emoji(self):
        self.client.post(
            reverse('teacher:section_rename', args=[self.section.pk]),
            {'title': 'Renamed'},
        )
        self.section.refresh_from_db()
        self.assertEqual(self.section.emoji, '🐍')

    def test_invalid_fields_do_not_partially_update_or_create_sections(self):
        for payload in (
            {'title': 'Changed', 'emoji': 'x' * 33},
            {'title': 'Changed', 'emoji': 'devicon:python:missing'},
            {'title': 'Changed', 'emoji': 'devicon:../../secrets:original'},
            {'title': 'Changed', 'emoji': 'heroicons:24-outline:../../secrets'},
            {'title': 'x' * 201, 'emoji': '🚀'},
            {'title': '   ', 'emoji': '🚀'},
        ):
            with self.subTest(payload=payload):
                self.client.post(
                    reverse('teacher:section_rename', args=[self.section.pk]),
                    payload,
                )
                self.section.refresh_from_db()
                self.assertEqual(self.section.title, 'Basics')
                self.assertEqual(self.section.emoji, '🐍')
                self.client.post(reverse('teacher:section_create'), {
                    'course_id': self.course.pk, **payload,
                })
                self.assertEqual(self.course.sections.count(), 1)

    def test_view_only_teacher_cannot_change_emoji(self):
        self.client.force_login(self.viewer)
        payload = {'title': 'Changed', 'emoji': '🚀'}
        response = self.client.post(
            reverse('teacher:section_rename', args=[self.section.pk]), payload,
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.post(reverse('teacher:section_create'), {
            'course_id': self.course.pk, **payload,
        })
        self.assertEqual(response.status_code, 403)
        self.section.refresh_from_db()
        self.assertEqual(self.section.emoji, '🐍')
        self.assertEqual(self.course.sections.count(), 1)

    def test_teacher_pages_show_emoji_and_editor_preloads_it(self):
        response = self.client.get(reverse(
            'teacher:course_edit', args=[self.course.pk],
        ))
        self.assertContains(response, 'data-section-emoji="🐍"')
        self.assertContains(response, 'id="renameSectionEmoji" name="emoji"')
        self.assertContains(response, 'id="sectionEmoji" name="emoji"')
        self.assertContains(response, 'type="hidden" id="renameSectionEmoji"')
        self.assertContains(response, 'data-source="/static/vendor/emoji-data/data.json"', count=2)
        self.assertContains(response, '/static/vendor/emoji-picker-element/picker.js')
        self.assertContains(response, '/static/js/section-emoji-picker.js')
        self.assertContains(response, reverse('teacher:section_icon_options'))
        self.assertNotContains(response, 'id="section-icon-catalog"')
        self.assertNotContains(response, '/static/vendor/devicon/python/python-original.svg')
        self.assertNotContains(response, '/static/vendor/heroicons/24/outline/academic-cap.svg')
        self.assertNotContains(response, 'data-section-emoji="📚"')
        self.assertContains(
            response, '<span class="section-icon-frame" aria-hidden="true">🐍</span>', html=True,
        )
        response = self.client.get(reverse(
            'teacher:course_manage', args=[self.course.pk],
        ))
        self.assertEqual(response.context['assignment_sections'][0]['emoji'], '🐍')
        self.assertContains(response, '🐍')

    def test_icon_options_serves_searchable_local_assets_as_json(self):
        url = reverse('teacher:section_icon_options')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        icons = {icon['name']: icon for icon in response.json()}
        python = icons['devicon:python:original']
        self.assertEqual(python['url'], '/static/vendor/devicon/python/python-original.svg')
        self.assertIn('python', python['shortcodes'])
        self.assertEqual(python['filter'], 'devicon')
        self.assertEqual(icons['heroicons:24-outline:document-text']['filter'], 'files')
        self.assertEqual(icons['heroicons:24-solid:document-text']['filter'], 'files')
        self.assertEqual(self.client.post(url).status_code, 405)

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from progress.models import CourseEnrollment, EpisodeReadStatus, QuizSubmission
from .models import Course, Episode, Section


class SectionPresentationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = get_user_model().objects.create_user(username='section-student')
        cls.course = Course.objects.create(
            title='Python', description='Course', is_published=True,
        )
        cls.section = Section.objects.create(
            course=cls.course, title='Basics', emoji='🐍',
        )
        cls.empty_section = Section.objects.create(
            course=cls.course, title='Coming soon', order=1,
        )
        cls.episode = Episode.objects.create(
            section=cls.section, title='First lesson', type='material',
        )

    def setUp(self):
        self.client.force_login(self.student)

    def test_overview_and_dashboard_start_with_all_sections_collapsed(self):
        for route in ('courses:course_overview', 'courses:course_dashboard'):
            with self.subTest(route=route):
                if route == 'courses:course_dashboard':
                    CourseEnrollment.objects.create(
                        user=self.student, course=self.course,
                    )
                response = self.client.get(reverse(route, args=[self.course.pk]))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'aria-expanded="false"', count=2)
                self.assertNotContains(response, 'class="collapse show"')
                for section in (self.section, self.empty_section):
                    target = f'section-episodes-{section.pk}'
                    self.assertContains(response, f'data-bs-target="#{target}"')
                    self.assertContains(response, f'aria-controls="{target}"')
                    self.assertContains(response, f'<div class="collapse" id="{target}">')
                self.assertContains(
                    response,
                    '<span aria-hidden="true">'
                    '<span class="section-icon-frame" aria-hidden="true">🐍</span>'
                    '</span> Basics',
                    html=True,
                )
                self.assertContains(response, 'First lesson')
                self.assertContains(response, 'No episodes yet')

    def test_learning_sidebar_shows_emoji_before_section_title(self):
        CourseEnrollment.objects.create(user=self.student, course=self.course)
        response = self.client.get(reverse(
            'courses:learning_interface_episode',
            args=[self.course.pk, self.episode.pk],
        ))
        self.assertEqual(response.status_code, 200)
        self.assertRegex(
            response.content.decode(),
            r'<span class="me-2" aria-hidden="true">'
            r'<span class="section-icon-frame" aria-hidden="true">🐍</span>\s*</span>\s*Basics',
        )
        self.assertEqual(response.context['expanded_section_id'], self.section.pk)

    def test_custom_icons_render_as_local_images_on_all_student_pages(self):
        for value, path in (
            ('devicon:python:original', 'devicon/python/python-original.svg'),
            ('heroicons:24-outline:academic-cap', 'heroicons/24/outline/academic-cap.svg'),
        ):
            self.section.emoji = value
            self.section.save(update_fields=['emoji'])
            CourseEnrollment.objects.filter(user=self.student, course=self.course).delete()
            for route, args in (
                ('courses:course_overview', [self.course.pk]),
                ('courses:course_dashboard', [self.course.pk]),
                ('courses:learning_interface_episode', [self.course.pk, self.episode.pk]),
            ):
                with self.subTest(icon=value, route=route):
                    if route == 'courses:course_dashboard':
                        CourseEnrollment.objects.create(user=self.student, course=self.course)
                    response = self.client.get(reverse(route, args=args))
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, f'src="/static/vendor/{path}"')
                    self.assertNotContains(response, value)
                    if value.startswith('heroicons:'):
                        self.assertContains(response, 'section-icon-heroicons')

    def test_emoji_is_escaped_on_student_pages(self):
        self.section.emoji = '<img src=x onerror=alert(1)>'
        self.section.save(update_fields=['emoji'])
        response = self.client.get(reverse(
            'courses:course_overview', args=[self.course.pk],
        ))
        self.assertContains(response, '&lt;img src=x onerror=alert(1)&gt;')
        self.assertNotContains(response, self.section.emoji)


class QuizLearningInterfaceTests(TestCase):
    def setUp(self):
        self.student = get_user_model().objects.create_user(
            username='student',
            email='student@example.com',
            password='test-password',
        )
        self.course = Course.objects.create(
            title='Python Basics',
            description='A test course',
            creator=self.student,
            is_published=True,
            enrollment_mode='open',
        )
        self.section = Section.objects.create(
            course=self.course,
            title='Syntax',
            order=1,
        )
        self.episode = Episode.objects.create(
            section=self.section,
            title='Syntax Quiz',
            type='quiz',
            order=1,
            info_page_content=(
                '## Which function prints output?\n'
                '>+ print()\n'
                '> echo()\n'
                '> console.log()\n'
                '> printf()'
            ),
        )
        self.code_episode = Episode.objects.create(
            section=self.section,
            title='Read two numbers',
            type='code',
            order=2,
            info_page_content='## Input\n\n```python\nvalue = input()\n```',
            starter_code='value = input()\nprint(value)',
            reference_sheet_content=(
                '## Input\n```python\nvalue = input()\n```\n'
                '- `input()` returns a string'
            ),
            code_oj_enabled=True,
            code_oj_testcases='[{"input":"1","expected":"1"}]',
        )
        self.client.force_login(self.student)

    def test_quiz_workspace_has_one_control_set(self):
        response = self.client.get(
            reverse(
                'courses:learning_interface_episode',
                args=[self.course.id, self.episode.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertContains(response, 'class="card quiz-workspace"')
        self.assertEqual(html.count('id="quiz-prev"'), 1)
        self.assertEqual(html.count('id="quiz-next"'), 1)
        self.assertEqual(html.count('id="quiz-submit-btn"'), 1)
        self.assertNotIn('quiz-prev-bottom', html)
        self.assertNotIn('quiz-next-bottom', html)
        self.assertNotIn('quizSubmitHeaderBtn', html)

    def test_quiz_workspace_includes_adaptive_choice_layout(self):
        response = self.client.get(
            reverse(
                'courses:learning_interface_episode',
                args=[self.course.id, self.episode.id],
            )
        )

        self.assertContains(response, 'function getChoiceLayoutClass(choices)')
        self.assertContains(response, 'quiz-choices-grid')
        self.assertContains(response, '@container (max-width: 720px)')

    def test_quiz_source_is_json_escaped_before_embedding_in_the_page(self):
        self.episode.info_page_content = (
            '## Assemble safely\n'
            '```quiz-cba html\n'
            '</textarea><script>window.quizPwned = true</script>\n'
            '```'
        )
        self.episode.save(update_fields=['info_page_content'])

        response = self.client.get(
            reverse(
                'courses:learning_interface_episode',
                args=[self.course.id, self.episode.id],
            )
        )

        html = response.content.decode()
        self.assertNotIn('</textarea><script>window.quizPwned', html)
        self.assertIn(r'\u003C', html)
        self.assertNotIn('const markdownContent =', html)

    def test_pending_quiz_submission_shows_status_without_taking_controls(self):
        QuizSubmission.objects.create(
            user=self.student,
            episode=self.episode,
            answers='{"questions": [{"type": "mcq", "selectedIndex": 0}]}',
        )

        response = self.client.get(
            reverse(
                'courses:learning_interface_episode',
                args=[self.course.id, self.episode.id],
            )
        )

        self.assertContains(response, 'Quiz Submitted')
        self.assertNotContains(response, 'id="quiz-prev"')
        self.assertNotContains(response, 'id="quiz-next"')
        self.assertNotContains(response, 'id="quiz-submit-btn"')

    def test_released_quiz_submission_renders_review_without_submit_button(self):
        QuizSubmission.objects.create(
            user=self.student,
            episode=self.episode,
            answers='{"questions": [{"type": "mcq", "selectedIndex": 0}]}',
            released_at=timezone.now(),
        )

        response = self.client.get(
            reverse(
                'courses:learning_interface_episode',
                args=[self.course.id, self.episode.id],
            )
        )

        self.assertContains(response, 'id="quiz-submission-data"')
        self.assertContains(response, 'Submitted and reviewed — results available.')
        self.assertNotContains(response, 'id="quiz-submit-btn"')

    def test_code_workspace_uses_shared_markdown_and_reference_styles(self):
        response = self.client.get(
            reverse(
                'courses:learning_interface_episode',
                args=[self.course.id, self.code_episode.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '/static/css/markdown.css')
        self.assertContains(response, '/static/css/reference-sheet.css')
        self.assertContains(
            response,
            'id="reference-content" class="markdown-body reference-sheet"',
        )

    def test_code_workspace_uses_starter_code_after_student_work(self):
        response = self.client.get(
            reverse(
                'courses:learning_interface_episode',
                args=[self.course.id, self.code_episode.id],
            )
        )

        self.assertContains(
            response,
            "const starterCode = 'value \\u003D input()\\u000Aprint(value)' || fallbackStarterCode;",
        )
        self.assertContains(
            response,
            "const fallbackStarterCode = '# Write your Python code here\\n';",
        )
        self.assertContains(
            response,
            "const usableSavedCode = savedCode === fallbackStarterCode ? '' : savedCode;",
        )
        self.assertContains(
            response,
            'usableSavedCode || uploadedCode || starterCode;',
        )

    def test_code_episodes_default_to_the_generic_starter_code(self):
        code_episode = Episode.objects.create(
            section=self.section,
            title='New code episode',
            type='code',
            order=3,
        )

        self.assertEqual(
            code_episode.starter_code,
            '# Write your Python code here\n',
        )

    def test_course_dashboard_ignores_episodes_excluded_from_progress(self):
        excluded_episode = Episode.objects.create(
            section=self.section,
            title='Optional reference',
            type='material',
            counts_toward_progress=False,
        )
        CourseEnrollment.objects.get_or_create(
            user=self.student,
            course=self.course,
        )
        EpisodeReadStatus.objects.create(
            user=self.student,
            episode=self.episode,
            is_read=True,
        )
        EpisodeReadStatus.objects.create(
            user=self.student,
            episode=excluded_episode,
            is_read=True,
        )

        response = self.client.get(
            reverse('courses:course_dashboard', args=[self.course.id])
        )

        self.assertEqual(response.context['total_episodes'], 2)
        self.assertEqual(response.context['read_episodes'], 1)
        self.assertEqual(response.context['progress_percentage'], 50.0)

    def test_sidebar_expands_section_containing_current_episode(self):
        second_section = Section.objects.create(
            course=self.course,
            title='Functions',
            order=2,
        )
        second_section_episode = Episode.objects.create(
            section=second_section,
            title='Defining Functions',
            type='material',
            order=1,
        )

        response = self.client.get(
            reverse(
                'courses:learning_interface_episode',
                args=[self.course.id, second_section_episode.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['expanded_section_id'], second_section.id)
        html = response.content.decode()
        self.assertRegex(
            html,
            rf'<button class="accordion-button collapsed"[^>]*'
            rf'data-bs-target="#section{self.section.id}"[^>]*'
            rf'aria-expanded="false"',
        )
        self.assertRegex(
            html,
            rf'<button class="accordion-button"[^>]*'
            rf'data-bs-target="#section{second_section.id}"[^>]*'
            rf'aria-expanded="true"',
        )
        self.assertRegex(
            html,
            rf'<div id="section{second_section.id}"\s+'
            rf'class="accordion-collapse collapse show"',
        )

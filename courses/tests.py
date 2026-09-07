from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from progress.models import QuizSubmission
from .models import Course, Episode, Section


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

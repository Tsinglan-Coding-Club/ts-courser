import json
import re
from html.parser import HTMLParser

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from courses.models import Course, Episode, Section
from progress.models import CourseEnrollment, QuizSubmission
from teacher.views import _cba_tokens_equivalent, _parse_quiz_markdown


class FormScopeParser(HTMLParser):
    """Record whether selected elements are parsed inside #episodeForm."""

    VOID_ELEMENTS = {
        'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
        'link', 'meta', 'param', 'source', 'track', 'wbr',
    }

    def __init__(self, targets):
        super().__init__()
        self.targets = set(targets)
        self.stack = []
        self.inside_episode_form = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        element_id = attrs.get('id')
        if element_id in self.targets:
            self.inside_episode_form[element_id] = any(
                open_tag == 'form' and open_id == 'episodeForm'
                for open_tag, open_id in self.stack
            )
        if tag not in self.VOID_ELEMENTS:
            self.stack.append((tag, element_id))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break


class AssignmentReviewTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='teacher',
            email='teacher@example.com',
            password='password',
            role='teacher',
            is_verified_teacher=True,
        )
        self.first_student = User.objects.create_user(
            username='first-student',
            email='first@example.com',
            password='password',
        )
        self.second_student = User.objects.create_user(
            username='second-student',
            email='second@example.com',
            password='password',
        )
        self.course = Course.objects.create(
            title='Course',
            description='Description',
            creator=self.teacher,
        )
        section = Section.objects.create(course=self.course, title='Section')
        self.episode = Episode.objects.create(
            section=section,
            title='Quiz',
            type='quiz',
            info_page_content=(
                '## Select all valid names\n'
                '>* alpha\n'
                '>* beta\n'
                '> gamma\n\n'
                '## Put the steps in order\n'
                '>3 implement\n'
                '>1 plan\n'
                '>4 verify\n'
                '>2 design'
            ),
        )
        for student in (self.first_student, self.second_student):
            CourseEnrollment.objects.create(user=student, course=self.course)

        QuizSubmission.objects.create(
            user=self.first_student,
            episode=self.episode,
            answers=json.dumps({
                'questions': [
                    {'type': 'mrq', 'selectedIds': [0, 1]},
                    {'type': 'srt', 'selectedIds': [1, 3, 0, 2]},
                ],
            }),
        )
        QuizSubmission.objects.create(
            user=self.second_student,
            episode=self.episode,
            answers=json.dumps({
                'questions': [
                    {'type': 'mrq', 'selectedIds': [0, 2]},
                    {'type': 'srt', 'selectedIds': [2, 0, 1, 3]},
                ],
            }),
        )
        self.client.force_login(self.teacher)

    def test_quiz_form_save_normalizes_crlf_without_losing_mixed_types(self):
        markdown = (
            '## Code\n```quiz-cba python\nprint(name)\n```\n\n'
            '## Single\n>+ yes\n> no\n\n'
            '## Multiple\n>* alpha\n>* beta\n> gamma\n\n'
            '## Sort\n>2 second\n>1 first\n\n'
            '## Explain\n>= reference'
        )
        posted = markdown.replace('\n', '\r\n')
        expected_types = ['cba', 'mcq', 'mrq', 'srt', 'frq']
        self.assertEqual(
            [q['type'] for q in _parse_quiz_markdown(posted)], expected_types
        )
        response = self.client.post(
            reverse('teacher:episode_edit', args=[self.episode.id]),
            {'title': 'Mixed quiz', 'type': 'quiz', 'order': 1,
             'info_page_content': posted},
        )
        self.assertEqual(response.status_code, 302)
        self.episode.refresh_from_db()
        self.assertEqual(self.episode.info_page_content, markdown)
        self.assertEqual(
            [q['type'] for q in _parse_quiz_markdown(self.episode.info_page_content)],
            expected_types,
        )

    def test_cba_review_accepts_interchanged_equal_tokens_across_rows(self):
        self.episode.info_page_content = (
            '## Names\r\n```quiz-cba python\r\n'
            'name = name\r\n    name = name\r\n```'
        )
        self.episode.save(update_fields=['info_page_content'])
        submission = QuizSubmission.objects.get(
            user=self.first_student, episode=self.episode
        )
        url = reverse('teacher:assignment_review', args=[self.course.id, self.episode.id])
        for ids, correct in [
            ([['l1c2', 'l1c1', 'l1c0'], ['l0c2', 'l0c1', 'l0c0']], True),
            ([['l0c0', 'l0c1', 'l0c0'], ['l1c0', 'l1c1', 'l1c2']], False),
            ([['l0c1', 'l0c0', 'l0c2'], ['l1c0', 'l1c1', 'l1c2']], False),
        ]:
            with self.subTest(ids=ids):
                submission.answers = json.dumps({'questions': [{'type': 'cba', 'tokenIds': ids}]})
                submission.save(update_fields=['answers'])
                response = self.client.get(url, {'user_id': self.first_student.id})
                question = response.context['selected_questions'][0]
                self.assertEqual(question['is_correct'], correct)
                if correct:
                    self.assertTrue(all(
                        token['positionCorrect']
                        for line in question['student_lines'] for token in line['tokens']
                    ))

    def test_switching_students_renders_selected_choices_from_requested_submission(self):
        url = reverse(
            'teacher:assignment_review',
            args=[self.course.id, self.episode.id],
        )

        first_response = self.client.get(
            url, {'user_id': self.first_student.id}
        )
        second_response = self.client.get(
            url, {'user_id': self.second_student.id}
        )

        self.assertEqual(
            first_response.context['selected_submission'].user,
            self.first_student,
        )
        self.assertEqual(
            second_response.context['selected_submission'].user,
            self.second_student,
        )

        first_multiple_choice = first_response.context['selected_questions'][0]
        self.assertEqual(
            (
                first_multiple_choice['choices'][1]['isSelected'],
                first_multiple_choice['choices'][1]['rowClass'],
            ),
            (True, 'student-selected correct'),
        )
        multiple_choice = second_response.context['selected_questions'][0]
        self.assertFalse(multiple_choice['is_correct'])
        self.assertEqual(
            [
                (choice['isSelected'], choice['rowClass'])
                for choice in multiple_choice['choices']
            ],
            [
                (True, 'student-selected correct'),
                (False, 'correct-answer'),
                (True, 'student-selected wrong-student'),
            ],
        )
        self.assertContains(
            second_response,
            'aria-label="Correct answer, not selected by student"',
        )
        self.assertContains(
            second_response,
            'aria-label="Selected by student; incorrect"',
        )

        second_html = second_response.content.decode()
        self.assertRegex(
            second_html,
            rf'href="\?user_id={self.second_student.id}"\s+'
            rf'class="[^"]*\bactive\b[^"]*"',
        )
        self.assertIsNone(re.search(
            rf'href="\?user_id={self.first_student.id}"\s+'
            rf'class="[^"]*\bactive\b[^"]*"',
            second_html,
        ))

        first_sorting_question = first_response.context['selected_questions'][1]
        self.assertTrue(first_sorting_question['is_correct'])
        sorting_question = second_response.context['selected_questions'][1]
        self.assertFalse(sorting_question['is_correct'])
        self.assertEqual(
            [choice['text'] for choice in sorting_question['student_choices']],
            ['verify', 'implement', 'plan', 'design'],
        )

    def test_malformed_choice_ids_do_not_crash_assignment_review(self):
        submission = QuizSubmission.objects.get(
            user=self.second_student,
            episode=self.episode,
        )
        submission.answers = json.dumps({
            'questions': [
                {'type': 'mrq', 'selectedIds': 3},
                {'type': 'srt', 'selectedIds': {'unexpected': 'mapping'}},
            ],
        })
        submission.save(update_fields=['answers'])

        response = self.client.get(
            reverse(
                'teacher:assignment_review',
                args=[self.course.id, self.episode.id],
            ),
            {'user_id': self.second_student.id},
        )

        self.assertEqual(response.status_code, 200)
        questions = response.context['selected_questions']
        self.assertFalse(questions[0]['is_correct'])
        self.assertFalse(any(
            choice['isSelected'] for choice in questions[0]['choices']
        ))
        self.assertFalse(questions[1]['is_correct'])
        self.assertEqual(questions[1]['student_choices'], [])

    def _use_cba_quiz(self, answer, indent_merged=False):
        config = {
            'v': 1,
            'language': 'python',
            'indentation': 'sortable',
            'lines': [
                {'cuts': [3, 9], 'hints': [True, False]},
                {
                    'cuts': [2, 4],
                    'hints': [False, False],
                    'indentMerged': indent_merged,
                },
            ],
        }
        self.episode.info_page_content = (
            '## Assemble the program\n'
            'Keep the provided keyword in place.\n\n'
            '```quiz-cba python\n'
            'if ready:\n'
            '    go()\n'
            '```\n'
            '```quiz-cba-config\n'
            f'{json.dumps(config)}\n'
            '```'
        )
        self.episode.save(update_fields=['info_page_content'])
        submission = QuizSubmission.objects.get(
            user=self.first_student,
            episode=self.episode,
        )
        submission.answers = json.dumps({'questions': [answer]})
        submission.save(update_fields=['answers'])
        return submission

    def test_cba_review_strictly_grades_each_movable_line(self):
        self._use_cba_quiz({
            'type': 'cba',
            'tokenIds': [['l0c1'], ['l1i', 'l1c0', 'l1c1']],
        })
        url = reverse(
            'teacher:assignment_review',
            args=[self.course.id, self.episode.id],
        )

        response = self.client.get(url, {'user_id': self.first_student.id})
        question = response.context['selected_questions'][0]

        self.assertTrue(question['is_correct'])
        self.assertTrue(question['answer_valid'])
        self.assertEqual(
            [token['id'] for token in question['student_lines'][0]['tokens']],
            ['l0c0', 'l0c1'],
        )
        self.assertTrue(question['student_lines'][0]['tokens'][0]['hint'])
        self.assertContains(response, 'Student assembly')
        self.assertContains(response, 'Provided hint')

        submission = QuizSubmission.objects.get(
            user=self.first_student,
            episode=self.episode,
        )
        submission.answers = json.dumps({
            'questions': [{
                'type': 'cba',
                'tokenIds': [['l0c1'], ['l1c1', 'l1c0', 'l1i']],
            }],
        })
        submission.save(update_fields=['answers'])
        response = self.client.get(url, {'user_id': self.first_student.id})
        question = response.context['selected_questions'][0]

        self.assertFalse(question['is_correct'])
        self.assertTrue(question['answer_valid'])
        self.assertFalse(
            question['student_lines'][1]['tokens'][0]['positionCorrect']
        )
        self.assertContains(response, 'Incorrect position')

    def test_cba_review_rejects_unknown_duplicate_and_wrong_shape_payloads(self):
        malformed_payloads = (
            [['l0c1'], ['l1i', 'unknown']],
            [['l0c1'], ['l0c1', 'l1i']],
            [['l0c1']],
            {'line': ['l0c1']},
        )
        url = reverse(
            'teacher:assignment_review',
            args=[self.course.id, self.episode.id],
        )

        for payload in malformed_payloads:
            with self.subTest(payload=payload):
                self._use_cba_quiz({'type': 'cba', 'tokenIds': payload})
                response = self.client.get(
                    url, {'user_id': self.first_student.id}
                )
                question = response.context['selected_questions'][0]
                self.assertEqual(response.status_code, 200)
                self.assertFalse(question['answer_valid'])
                self.assertFalse(question['is_correct'])
                self.assertContains(response, 'Invalid submission payload')

    def test_cba_review_grades_merged_indent_as_first_chunk(self):
        self._use_cba_quiz(
            {
                'type': 'cba',
                'tokenIds': [['l0c1'], ['l1c0', 'l1c1']],
            },
            indent_merged=True,
        )

        response = self.client.get(
            reverse(
                'teacher:assignment_review',
                args=[self.course.id, self.episode.id],
            ),
            {'user_id': self.first_student.id},
        )
        question = response.context['selected_questions'][0]

        self.assertTrue(question['is_correct'])
        self.assertNotIn('l1i', {choice['id'] for choice in question['choices']})
        merged = next(
            choice for choice in question['choices'] if choice['id'] == 'l1c0'
        )
        self.assertEqual(merged['text'], '    go')


class CBAQuizParserTests(TestCase):
    def test_token_equivalence_preserves_strings_grouping_and_indentation(self):
        def token(text, kind='token', leading=''):
            return {'text': text, 'kind': kind, 'leadingIndent': leading}

        self.assertTrue(_cba_tokens_equivalent(token('name'), token(' name ')))
        self.assertFalse(_cba_tokens_equivalent(token('"a b"'), token('"a  b"')))
        self.assertFalse(_cba_tokens_equivalent(token('name + name'), token('name')))
        self.assertFalse(_cba_tokens_equivalent(token('    name', leading='    '), token('name')))
        self.assertFalse(_cba_tokens_equivalent(token('    ', 'indent'), token('        ', 'indent')))
        self.assertTrue(_cba_tokens_equivalent(token('    ', 'indent'), token('    ', 'indent')))

    def test_indent_merge_combines_indent_with_first_token_and_hint(self):
        config = {
            'v': 1,
            'language': 'python',
            'indentation': 'visible',
            'lines': [{
                'cuts': [5, 7],
                'hints': [False, False],
                'indentMerged': True,
                'indentHint': True,
            }],
        }
        markdown = (
            '## Assemble the indented line\n'
            '```quiz-cba python\n'
            '    print()\n'
            '```\n'
            '```quiz-cba-config\n'
            f'{json.dumps(config)}\n'
            '```'
        )

        question = _parse_quiz_markdown(markdown)[0]

        self.assertEqual(
            [choice['id'] for choice in question['choices']],
            ['l0c0', 'l0c1'],
        )
        self.assertEqual(question['choices'][0]['text'], '    print')
        self.assertTrue(question['choices'][0]['hint'])
        self.assertTrue(question['lines'][0]['indentMerged'])

    def test_non_boolean_indent_hint_invalidates_whole_config(self):
        config = {
            'v': 1,
            'language': 'python',
            'indentation': 'sortable',
            'lines': [{
                'cuts': [5, 7],
                'hints': [True, True],
                'indentMerged': True,
                'indentHint': 'true',
            }],
        }
        markdown = (
            '## Assemble the indented line\n'
            '```quiz-cba python\n'
            '    print()\n'
            '```\n'
            '```quiz-cba-config\n'
            f'{json.dumps(config)}\n'
            '```'
        )

        question = _parse_quiz_markdown(markdown)[0]

        self.assertEqual(question['indentation'], 'visible')
        self.assertIn('l0i', {choice['id'] for choice in question['choices']})
        self.assertFalse(question['lines'][0]['indentMerged'])

    def test_per_line_indent_hint_overrides_global_indentation(self):
        config = {
            'v': 1,
            'language': 'python',
            'indentation': 'sortable',
            'lines': [{
                'cuts': [5, 7],
                'hints': [False, False],
                'indentHint': True,
            }],
        }
        markdown = (
            '## Assemble the indented line\n'
            '```quiz-cba python\n'
            '    print()\n'
            '```\n'
            '```quiz-cba-config\n'
            f'{json.dumps(config)}\n'
            '```'
        )

        question = _parse_quiz_markdown(markdown)[0]
        indent = next(
            choice for choice in question['choices'] if choice['id'] == 'l0i'
        )

        self.assertTrue(indent['hint'])
        self.assertTrue(question['lines'][0]['indentHint'])

        config['indentation'] = 'visible'
        config['lines'][0]['indentHint'] = False
        markdown = markdown.replace(
            markdown.split('```quiz-cba-config\n', 1)[1].split('\n```', 1)[0],
            json.dumps(config),
        )
        question = _parse_quiz_markdown(markdown)[0]
        indent = next(
            choice for choice in question['choices'] if choice['id'] == 'l0i'
        )
        self.assertFalse(indent['hint'])

    def test_parses_unicode_cuts_visible_indent_and_fence_heading(self):
        code_lines = ['if 😀:', '    print("好")', '## stays in code']
        config = {
            'v': 1,
            'language': 'python',
            'indentation': 'visible',
            'lines': [
                {'cuts': [3, 5], 'hints': [True, False]},
                {'cuts': [5, 6, 9, 10], 'hints': [False] * 4},
                {'cuts': [len(code_lines[2])], 'hints': [False]},
            ],
        }
        markdown = (
            '## Complete this Unicode program\n'
            'The code heading must stay inside this question.\n'
            '```quiz-cba python\n'
            f'{code_lines[0]}\n{code_lines[1]}\n{code_lines[2]}\n'
            '```\n'
            '```quiz-cba-config\n'
            f'{json.dumps(config, ensure_ascii=False)}\n'
            '```\n\n'
            '## Ordinary question\n'
            '>+ yes\n'
            '> no'
        )

        questions = _parse_quiz_markdown(markdown)

        self.assertEqual([question['type'] for question in questions], ['cba', 'mcq'])
        cba = questions[0]
        self.assertEqual(cba['code'], '\n'.join(code_lines))
        self.assertEqual(cba['language'], 'python')
        self.assertEqual(cba['indentation'], 'visible')
        self.assertEqual(
            [choice['text'] for choice in cba['choices'][:2]],
            ['if ', '😀:'],
        )
        indent = next(choice for choice in cba['choices'] if choice['id'] == 'l1i')
        self.assertTrue(indent['hint'])
        self.assertEqual(indent['displayText'], '····')
        self.assertIn('The code heading', cba['question'])

    def test_invalid_config_falls_back_to_lossless_generic_tokens(self):
        markdown = (
            '## Repair the program\n'
            '```quiz-cba javascript\n'
            '  const label = "😀 ok";\n'
            '```\n'
            '```quiz-cba-config\n'
            '{"v":1,"language":"javascript","indentation":"sortable",'
            '"lines":[{"cuts":[999],"hints":[true]}]}\n'
            '```'
        )

        question = _parse_quiz_markdown(markdown)[0]
        line_choices = [
            choice for choice in question['choices']
            if choice['line'] == 0 and choice['kind'] == 'token'
        ]

        self.assertEqual(question['type'], 'cba')
        self.assertEqual(question['indentation'], 'visible')
        self.assertEqual(
            ''.join(choice['text'] for choice in line_choices),
            'const label = "😀 ok";',
        )
        self.assertTrue(all(not choice['hint'] for choice in line_choices))

    def test_legacy_fenced_code_heading_does_not_split_question(self):
        markdown = (
            '## Explain this snippet\n'
            '```text\n'
            '## not a quiz heading\n'
            '```\n'
            '> answer\n\n'
            '## Next\n'
            '>+ correct'
        )

        questions = _parse_quiz_markdown(markdown)

        self.assertEqual(len(questions), 2)
        self.assertIn('## not a quiz heading', questions[0]['question'])


class CodeEpisodeEditorTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='code-teacher',
            email='code-teacher@example.com',
            password='password',
            role='teacher',
            is_verified_teacher=True,
        )
        self.course = Course.objects.create(
            title='Python',
            description='Code course',
            creator=self.teacher,
        )
        section = Section.objects.create(
            course=self.course,
            title='Input and output',
        )
        self.episode = Episode.objects.create(
            section=section,
            title='Echo',
            type='code',
            info_page_content='```python\nprint(input())\n```',
            starter_code='message = input()\nprint(message)',
            reference_sheet_content=(
                '## Input\n```python\nvalue = input()\n```'
            ),
            code_oj_enabled=True,
            code_oj_testcases='[{"input":"hi","expected":"hi"}]',
        )
        self.client.force_login(self.teacher)

    def test_code_cards_and_fields_remain_inside_episode_form(self):
        response = self.client.get(
            reverse('teacher:episode_edit', args=[self.episode.id])
        )

        self.assertEqual(response.status_code, 200)
        targets = {
            'codeLayoutCard',
            'showInteractive',
            'showReference',
            'starterCodeCard',
            'starterCode',
            'codeOJCard',
            'codeOJEnabled',
            'codeOJTestCasesInput',
            'referenceSheetCard',
            'refEditor',
        }
        parser = FormScopeParser(targets)
        parser.feed(response.content.decode())
        self.assertEqual(parser.inside_episode_form, {
            target: True for target in targets
        })

    def test_code_editor_loads_shared_styles_and_collapsible_test_cases(self):
        response = self.client.get(
            reverse('teacher:episode_edit', args=[self.episode.id])
        )

        self.assertEqual(
            response.content.decode().count(
                'class="card mb-4 episode-editor-card'
            ),
            10,
        )
        self.assertContains(response, '/static/css/markdown.css')
        self.assertContains(response, '/static/css/reference-sheet.css')
        self.assertContains(
            response,
            'class="md-preview reference-sheet" id="refPreview"',
        )
        self.assertContains(response, 'class="oj-testcase-toggle"')
        self.assertContains(response, 'id="ojTestCaseCount"')
        self.assertContains(response, 'Automated Code Testing')
        self.assertContains(response, 'Enable automated tests')
        self.assertContains(response, 'Starter Code')
        self.assertContains(response, 'message = input()')
        self.assertNotContains(response, 'Online Judge (OJ)')
        self.assertNotContains(response, 'Enable OJ mode')
        self.assertNotContains(response, 'episode-editor-tail')

    def test_starter_code_is_saved_from_the_episode_editor(self):
        starter_code = 'name = input()\nprint(f"Hello, {name}")'
        response = self.client.post(
            reverse('teacher:episode_edit', args=[self.episode.id]),
            {
                'title': self.episode.title,
                'type': 'code',
                'order': self.episode.order,
                'info_page_content': self.episode.info_page_content,
                'starter_code': starter_code,
                'code_oj_testcases': self.episode.code_oj_testcases,
                'reference_sheet_content': self.episode.reference_sheet_content,
            },
        )

        self.assertRedirects(
            response,
            reverse('teacher:course_edit', args=[self.course.id]),
        )
        self.episode.refresh_from_db()
        self.assertEqual(self.episode.starter_code, starter_code)

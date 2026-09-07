import json
from copy import deepcopy

from courses.quiz import token_id

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from courses.models import Course, Episode, Section, Tag
from progress.models import (
    CodeSubmission,
    CourseEnrollment,
    EpisodeReadStatus,
    QuizSubmission,
    UserProgress,
)


class ProgressAccessAndSubmissionTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='teacher',
            email='teacher@example.com',
            password='password',
            role='teacher',
            is_verified_teacher=True,
        )
        self.student = User.objects.create_user(
            username='student',
            email='student@example.com',
            password='password',
        )
        self.outsider = User.objects.create_user(
            username='outsider',
            email='outsider@example.com',
            password='password',
        )
        self.course = Course.objects.create(
            title='Course',
            description='Description',
            creator=self.teacher,
            is_published=True,
            auto_release_results=True,
        )
        self.section = Section.objects.create(course=self.course, title='Section')
        self.material = Episode.objects.create(
            section=self.section, title='Material', type='material'
        )
        self.code_episode = Episode.objects.create(
            section=self.section, title='Code', type='code'
        )
        self.quiz_episode = Episode.objects.create(
            section=self.section, title='Quiz', type='quiz',
            info_page_content='## Pick one\n>+ Yes\n> No'
        )
        self.cba_episode = Episode.objects.create(
            section=self.section,
            title='Code assembly quiz',
            type='quiz',
            quiz_require_all=True,
            info_page_content=(
                '## Assemble the conditional\n'
                '```quiz-cba python\n'
                'if ready:\n'
                '    print("go")\n'
                '```\n'
                '```quiz-cba-config\n'
                '{"v":1,"language":"python","indentation":"sortable",'
                '"lines":[{"cuts":[3,9],"hints":[false,false]},'
                '{"cuts":[5,6,10,11],"hints":[false,false,false,false]}]}\n'
                '```'
            ),
        )
        CourseEnrollment.objects.create(user=self.student, course=self.course)

    def wire_answers(self, answer):
        result = deepcopy(answer)
        for index, question in enumerate(result['questions']):
            if question['type'] == 'cba':
                question['tokenIds'] = [
                    [token_id(self.cba_episode, index, item) for item in line]
                    for line in question['tokenIds']
                ]
        return result

    def test_progress_endpoints_require_course_access(self):
        self.client.force_login(self.outsider)

        response = self.client.post(
            reverse('progress:update_progress'), {'episode_id': self.material.id}
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(UserProgress.objects.filter(user=self.outsider).exists())

        self.client.force_login(self.student)
        response = self.client.post(
            reverse('progress:mark_episode'),
            {'episode_id': self.material.id, 'is_read': 'true'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            EpisodeReadStatus.objects.get(
                user=self.student, episode=self.material
            ).is_read
        )

    def test_my_courses_renders_full_description_and_all_tags_for_css_overflow(self):
        description = ' '.join(f'description-{index}' for index in range(30))
        self.course.description = description
        self.course.save(update_fields=['description'])
        tags = [
            Tag.objects.create(name=f'Tag {index}', category='subject')
            for index in range(4)
        ]
        self.course.tags.set(tags)
        self.client.force_login(self.student)

        response = self.client.get(reverse('progress:my_courses'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, description)
        for tag in tags:
            self.assertContains(response, tag.name)
        self.assertContains(response, 'class="mb-3 course-tags"')

    def test_upload_stores_draft_without_creating_teacher_visible_submission(self):
        self.client.force_login(self.student)

        response = self.client.post(
            reverse('progress:upload_code'),
            {'episode_id': self.code_episode.id, 'code': 'print("draft")'},
        )

        self.assertEqual(response.status_code, 200)
        upload = CodeSubmission.objects.get(
            user=self.student, episode=self.code_episode
        )
        self.assertEqual(upload.code, 'print("draft")')
        self.assertFalse(upload.is_submitted)
        self.assertIsNone(upload.submitted_at)
        self.assertFalse(
            EpisodeReadStatus.objects.filter(
                user=self.student, episode=self.code_episode
            ).exists()
        )

    def test_formal_submission_promotes_uploaded_code(self):
        self.client.force_login(self.student)
        self.client.post(
            reverse('progress:upload_code'),
            {'episode_id': self.code_episode.id, 'code': 'print("draft")'},
        )

        response = self.client.post(
            reverse('progress:submit_code'),
            {
                'episode_id': self.code_episode.id,
                'code': 'print("final")',
                'test_results': json.dumps([{'passed': True}]),
            },
        )

        self.assertEqual(response.status_code, 200)
        submission = CodeSubmission.objects.get(
            user=self.student, episode=self.code_episode
        )
        self.assertEqual(submission.code, 'print("final")')
        self.assertTrue(submission.is_submitted)
        self.assertIsNotNone(submission.submitted_at)
        self.assertTrue(
            EpisodeReadStatus.objects.get(
                user=self.student, episode=self.code_episode
            ).is_read
        )

    def test_inherited_release_policy_uses_course_default_except_for_frq(self):
        self.client.force_login(self.student)
        mcq_answers = {'questions': [{'type': 'mcq', 'selectedIndex': 0}]}
        response = self.client.post(
            reverse('progress:submit_quiz'),
            {'episode_id': self.quiz_episode.id, 'answers': json.dumps(mcq_answers)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(
            QuizSubmission.objects.get(
                user=self.student, episode=self.quiz_episode
            ).released_at
        )

        QuizSubmission.objects.filter(
            user=self.student, episode=self.quiz_episode
        ).delete()
        self.quiz_episode.info_page_content = '## Explain\n>= Reference'
        self.quiz_episode.quiz_release_policy = 'manual'
        self.quiz_episode.save()
        response = self.client.post(
            reverse('progress:submit_quiz'),
            {
                'episode_id': self.quiz_episode.id,
                'answers': json.dumps({'questions': [{'type': 'frq', 'text': 'Answer'}]}),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(
            QuizSubmission.objects.get(
                user=self.student, episode=self.quiz_episode
            ).released_at
        )

    def test_immediate_episode_policy_releases_frq(self):
        self.quiz_episode.info_page_content = '## Explain\n>= Reference'
        self.quiz_episode.quiz_release_policy = 'immediate'
        self.quiz_episode.save()
        self.client.force_login(self.student)

        response = self.client.post(
            reverse('progress:submit_quiz'),
            {
                'episode_id': self.quiz_episode.id,
                'answers': json.dumps({'questions': [{'type': 'frq', 'text': 'Answer'}]}),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(
            QuizSubmission.objects.get(
                user=self.student, episode=self.quiz_episode
            ).released_at
        )

    def test_code_assembly_submission_validates_server_owned_token_ids(self):
        self.client.force_login(self.student)
        answer = {
            'questions': [{
                'type': 'cba',
                'tokenIds': [
                    ['l0c0', 'l0c1'],
                    ['l1i', 'l1c0', 'l1c1', 'l1c2', 'l1c3'],
                ],
            }],
        }

        response = self.client.post(
            reverse('progress:submit_quiz'),
            {'episode_id': self.cba_episode.id, 'answers': json.dumps(self.wire_answers(answer))},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(
            QuizSubmission.objects.get(
                user=self.student, episode=self.cba_episode
            ).released_at
        )

        incomplete = {
            'questions': [{
                'type': 'cba',
                'tokenIds': [[], []],
            }],
        }
        response = self.client.post(
            reverse('progress:submit_quiz'),
            {
                'episode_id': self.cba_episode.id,
                'answers': json.dumps(self.wire_answers(incomplete)),
            },
        )
        self.assertEqual(response.status_code, 400)

        overfilled_line = {
            'questions': [{
                'type': 'cba',
                'tokenIds': [[
                    'l0c0', 'l0c1', 'l1i', 'l1c0', 'l1c1', 'l1c2', 'l1c3',
                ], []],
            }],
        }
        response = self.client.post(
            reverse('progress:submit_quiz'),
            {
                'episode_id': self.cba_episode.id,
                'answers': json.dumps(self.wire_answers(overfilled_line)),
            },
        )
        self.assertEqual(response.status_code, 400)

        answer['questions'][0]['tokenIds'][0].append('unknown-token')
        response = self.client.post(
            reverse('progress:submit_quiz'),
            {'episode_id': self.cba_episode.id, 'answers': json.dumps(self.wire_answers(answer))},
        )
        self.assertEqual(response.status_code, 400)

    def test_code_assembly_submission_accepts_merged_indent_token(self):
        config = {
            'v': 1,
            'language': 'python',
            'indentation': 'sortable',
            'lines': [
                {'cuts': [3, 9], 'hints': [False, False]},
                {
                    'cuts': [5, 6, 10, 11],
                    'hints': [False, False, False, False],
                    'indentMerged': True,
                },
            ],
        }
        self.cba_episode.info_page_content = (
            '## Assemble the conditional\n'
            '```quiz-cba python\n'
            'if ready:\n'
            '    print("go")\n'
            '```\n'
            '```quiz-cba-config\n'
            f'{json.dumps(config)}\n'
            '```'
        )
        self.cba_episode.save(update_fields=['info_page_content'])
        self.client.force_login(self.student)
        answer = {
            'questions': [{
                'type': 'cba',
                'tokenIds': [
                    ['l0c0', 'l0c1'],
                    ['l1c0', 'l1c1', 'l1c2', 'l1c3'],
                ],
            }],
        }

        response = self.client.post(
            reverse('progress:submit_quiz'),
            {'episode_id': self.cba_episode.id, 'answers': json.dumps(self.wire_answers(answer))},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            QuizSubmission.objects.filter(
                user=self.student, episode=self.cba_episode
            ).exists()
        )

        answer['questions'][0]['tokenIds'][1].append('l1i')
        response = self.client.post(
            reverse('progress:submit_quiz'),
            {'episode_id': self.cba_episode.id, 'answers': json.dumps(self.wire_answers(answer))},
        )
        self.assertEqual(response.status_code, 400)

    def test_code_assembly_per_line_indent_hint_is_not_submitted(self):
        config = {
            'v': 1,
            'language': 'python',
            'indentation': 'sortable',
            'lines': [
                {'cuts': [3, 9], 'hints': [False, False]},
                {
                    'cuts': [5, 6, 10, 11],
                    'hints': [False, False, False, False],
                    'indentHint': True,
                },
            ],
        }
        self.cba_episode.info_page_content = (
            '## Assemble the conditional\n'
            '```quiz-cba python\n'
            'if ready:\n'
            '    print("go")\n'
            '```\n'
            '```quiz-cba-config\n'
            f'{json.dumps(config)}\n'
            '```'
        )
        self.cba_episode.save(update_fields=['info_page_content'])
        self.client.force_login(self.student)
        answer = {
            'questions': [{
                'type': 'cba',
                'tokenIds': [
                    ['l0c0', 'l0c1'],
                    ['l1c0', 'l1c1', 'l1c2', 'l1c3'],
                ],
            }],
        }

        response = self.client.post(
            reverse('progress:submit_quiz'),
            {'episode_id': self.cba_episode.id, 'answers': json.dumps(self.wire_answers(answer))},
        )
        self.assertEqual(response.status_code, 200)

        answer['questions'][0]['tokenIds'][1].insert(0, 'l1i')
        response = self.client.post(
            reverse('progress:submit_quiz'),
            {'episode_id': self.cba_episode.id, 'answers': json.dumps(self.wire_answers(answer))},
        )
        self.assertEqual(response.status_code, 400)

    def test_code_assembly_type_cannot_be_spoofed_to_change_release_logic(self):
        self.client.force_login(self.student)
        response = self.client.post(
            reverse('progress:submit_quiz'),
            {
                'episode_id': self.cba_episode.id,
                'answers': json.dumps({
                    'questions': [{'type': 'frq', 'text': 'pretend'}],
                }),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            QuizSubmission.objects.filter(
                user=self.student, episode=self.cba_episode
            ).exists()
        )

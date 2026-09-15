from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from courses.models import Course
from progress.models import CourseEnrollment


User = get_user_model()


class StudentManagementTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='teacher',
            email='teacher@example.com',
            password='password',
            role='teacher',
            is_verified_teacher=True,
        )
        self.other_teacher = User.objects.create_user(
            username='other-teacher',
            email='other@example.com',
            password='password',
            role='teacher',
            is_verified_teacher=True,
        )
        self.student = User.objects.create_user(
            username='student',
            email='student@example.com',
            password='password',
            role='student',
        )
        self.course = Course.objects.create(
            title='Test Course',
            description='A course for testing.',
            creator=self.teacher,
        )
        self.add_url = reverse('teacher:add_student')

    def test_course_owner_can_add_registered_student(self):
        self.client.force_login(self.teacher)

        response = self.client.post(self.add_url, {
            'course_id': self.course.id,
            'user_id': self.student.id,
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertTrue(CourseEnrollment.objects.filter(
            course=self.course,
            user=self.student,
        ).exists())

    def test_teacher_cannot_add_student_to_another_teachers_course(self):
        self.client.force_login(self.other_teacher)

        response = self.client.post(self.add_url, {
            'course_id': self.course.id,
            'user_id': self.student.id,
        })

        self.assertEqual(response.status_code, 403)
        self.assertFalse(CourseEnrollment.objects.exists())

    def test_non_student_account_cannot_be_added(self):
        self.client.force_login(self.teacher)

        response = self.client.post(self.add_url, {
            'course_id': self.course.id,
            'user_id': self.other_teacher.id,
        })

        self.assertEqual(response.status_code, 404)
        self.assertFalse(CourseEnrollment.objects.exists())

    def test_duplicate_enrollment_is_rejected(self):
        CourseEnrollment.objects.create(course=self.course, user=self.student)
        self.client.force_login(self.teacher)

        response = self.client.post(self.add_url, {
            'course_id': self.course.id,
            'user_id': self.student.id,
        })

        self.assertEqual(response.status_code, 409)
        self.assertEqual(CourseEnrollment.objects.count(), 1)

    def test_manage_page_only_lists_students_not_yet_enrolled(self):
        enrolled_student = User.objects.create_user(
            username='enrolled',
            email='enrolled@example.com',
            password='password',
            role='student',
        )
        CourseEnrollment.objects.create(
            course=self.course,
            user=enrolled_student,
        )
        self.client.force_login(self.teacher)

        response = self.client.get(reverse(
            'teacher:course_manage',
            args=[self.course.id],
        ))

        self.assertContains(response, self.student.email)
        self.assertContains(response, enrolled_student.email)
        available_students = list(response.context['available_students'])
        self.assertIn(self.student, available_students)
        self.assertNotIn(enrolled_student, available_students)

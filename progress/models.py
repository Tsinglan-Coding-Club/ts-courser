from django.db import models
from django.conf import settings
from courses.models import Course, Episode


class CourseEnrollment(models.Model):
    """
    Tracks which courses a user has enrolled in (added to their learning list).
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='enrolled_courses'
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='enrollments'
    )
    enrolled_at = models.DateTimeField(auto_now_add=True, help_text='When the user enrolled in this course')

    def __str__(self):
        return f"{self.user.username} enrolled in {self.course.title}"

    class Meta:
        unique_together = ['user', 'course']
        ordering = ['-enrolled_at']
        verbose_name_plural = 'Course Enrollments'


class UserProgress(models.Model):
    """
    Tracks a user's overall progress in a course.
    Records the current episode they're viewing.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='course_progress'
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='user_progress'
    )
    current_episode = models.ForeignKey(
        Episode,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text='The episode the user is currently viewing'
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {self.course.title}"

    class Meta:
        unique_together = ['user', 'course']
        verbose_name_plural = 'User Progress'


class EpisodeReadStatus(models.Model):
    """
    Tracks whether a user has marked an episode as read/unread.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='episode_read_statuses'
    )
    episode = models.ForeignKey(
        Episode,
        on_delete=models.CASCADE,
        related_name='read_statuses'
    )
    is_read = models.BooleanField(default=False)
    marked_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        status = "Read" if self.is_read else "Unread"
        return f"{self.user.username} - {self.episode.title} ({status})"

    class Meta:
        unique_together = ['user', 'episode']
        verbose_name_plural = 'Episode Read Statuses'


class QuizSubmission(models.Model):
    """
    Stores a student's submitted answers to a quiz episode.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='quiz_submissions'
    )
    episode = models.ForeignKey(
        Episode,
        on_delete=models.CASCADE,
        related_name='submissions'
    )
    answers = models.TextField(
        blank=True,
        help_text='JSON string of student answers'
    )
    frq_grades = models.TextField(
        blank=True, default='{}',
        help_text='JSON: question_index -> is_correct for FRQ grading'
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.episode.title}"

    class Meta:
        unique_together = ['user', 'episode']
        ordering = ['-submitted_at']

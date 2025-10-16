from django.db import models
from django.conf import settings
from courses.models import Course, Episode


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

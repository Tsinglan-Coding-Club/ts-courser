from django.db import models
from django.conf import settings
import uuid
import os


class Tag(models.Model):
    """
    Tags for categorizing courses (e.g., AP Calculus, A-Level Physics).
    """
    CATEGORY_CHOICES = [
        ('track', 'Track'),  # e.g., AP, A-Level
        ('subject', 'Subject'),  # e.g., Math, Physics
    ]

    name = models.CharField(max_length=50, unique=True)
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.category})"

    class Meta:
        ordering = ['category', 'name']


class Course(models.Model):
    """
    Main course model containing sections and episodes.
    """
    title = models.CharField(max_length=200)
    description = models.TextField()
    thumbnail = models.ImageField(
        upload_to='course_thumbnails/',
        null=True,
        blank=True
    )
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='created_courses'
    )
    tags = models.ManyToManyField(Tag, related_name='courses', blank=True)
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['-created_at']


class Section(models.Model):
    """
    A section within a course, containing multiple episodes.
    """
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='sections'
    )
    title = models.CharField(max_length=200)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.course.title} - {self.title}"

    class Meta:
        ordering = ['order']


def episode_pdf_path(instance, filename):
    """Generate unique filename for episode PDFs."""
    ext = os.path.splitext(filename)[1]
    unique_filename = f"{uuid.uuid4()}_{instance.id}{ext}"
    return os.path.join('episode_pdfs', unique_filename)


def answer_pdf_path(instance, filename):
    """Generate unique filename for answer PDFs."""
    ext = os.path.splitext(filename)[1]
    unique_filename = f"{uuid.uuid4()}_{instance.id}{ext}"
    return os.path.join('answer_pdfs', unique_filename)


class Episode(models.Model):
    """
    Individual learning unit: material, quiz, code, or paper.
    """
    TYPE_CHOICES = [
        ('material', 'Material'),
        ('quiz', 'Quiz'),
        ('code', 'Code'),
        ('paper', 'Paper'),
    ]

    section = models.ForeignKey(
        Section,
        on_delete=models.CASCADE,
        related_name='episodes'
    )
    title = models.CharField(max_length=200)
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    order = models.IntegerField(default=0)

    # Content fields
    info_page_content = models.TextField(
        null=True,
        blank=True,
        help_text='Markdown content for the info page'
    )
    content_pdf = models.FileField(
        upload_to=episode_pdf_path,
        null=True,
        blank=True,
        help_text='Main content PDF file'
    )
    answer_pdf = models.FileField(
        upload_to=answer_pdf_path,
        null=True,
        blank=True,
        help_text='Answer PDF (for quiz and paper types)'
    )

    # Code episode layout toggles
    show_interactive = models.BooleanField(
        default=True,
        help_text='Show the Interactive panel in code episodes'
    )
    show_reference = models.BooleanField(
        default=True,
        help_text='Show the Reference panel in code episodes'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.section.title} - {self.title} ({self.type})"

    class Meta:
        ordering = ['order', 'id']

    @property
    def has_content(self):
        """Check if episode has any content."""
        return bool(self.info_page_content or self.content_pdf)

    @property
    def course(self):
        """Get the parent course."""
        return self.section.course

from django.contrib import admin
from .models import Tag, Course, Section, Episode


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'created_at']
    list_filter = ['category']
    search_fields = ['name']


class SectionInline(admin.TabularInline):
    model = Section
    extra = 1
    fields = ['title', 'order']


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['title', 'creator', 'is_published', 'created_at']
    list_filter = ['is_published', 'created_at', 'tags']
    search_fields = ['title', 'description']
    filter_horizontal = ['tags']
    inlines = [SectionInline]

    def save_model(self, request, obj, form, change):
        if not change:  # If creating new object
            obj.creator = request.user
        super().save_model(request, obj, form, change)


class EpisodeInline(admin.TabularInline):
    model = Episode
    extra = 1
    fields = ['title', 'type', 'order', 'info_page_content', 'content_pdf', 'answer_pdf']


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ['title', 'course', 'order', 'created_at']
    list_filter = ['course']
    search_fields = ['title']
    inlines = [EpisodeInline]


@admin.register(Episode)
class EpisodeAdmin(admin.ModelAdmin):
    list_display = ['title', 'section', 'type', 'order', 'has_content', 'created_at']
    list_filter = ['type', 'section__course']
    search_fields = ['title', 'section__title']
    readonly_fields = ['created_at', 'updated_at']

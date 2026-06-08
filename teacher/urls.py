from django.urls import path
from . import views

app_name = 'teacher'

urlpatterns = [
    path('courses/', views.course_list, name='course_list'),
    path('courses/create/', views.course_create, name='course_create'),
    path('courses/<int:course_id>/edit/', views.course_edit, name='course_edit'),
    path('courses/<int:course_id>/delete/', views.course_delete, name='course_delete'),
    path('sections/create/', views.section_create, name='section_create'),
    path('sections/<int:section_id>/delete/', views.section_delete, name='section_delete'),
    path('sections/reorder/', views.section_reorder, name='section_reorder'),
    path('episodes/create/', views.episode_create, name='episode_create'),
    path('episodes/<int:episode_id>/edit/', views.episode_edit, name='episode_edit'),
    path('episodes/<int:episode_id>/delete/', views.episode_delete, name='episode_delete'),
    path('episodes/reorder/', views.episode_reorder, name='episode_reorder'),
    path('tags/create/', views.tag_create, name='tag_create'),
]

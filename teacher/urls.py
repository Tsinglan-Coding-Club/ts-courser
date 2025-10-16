from django.urls import path
from . import views

app_name = 'teacher'

urlpatterns = [
    path('courses/', views.course_list, name='course_list'),
    path('courses/create/', views.course_create, name='course_create'),
    path('courses/<int:course_id>/edit/', views.course_edit, name='course_edit'),
    path('sections/create/', views.section_create, name='section_create'),
    path('episodes/create/', views.episode_create, name='episode_create'),
    path('episodes/<int:episode_id>/edit/', views.episode_edit, name='episode_edit'),
]

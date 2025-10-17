from django.urls import path
from . import views

app_name = 'progress'

urlpatterns = [
    path('progress/update/', views.update_progress, name='update_progress'),
    path('progress/mark/', views.mark_episode, name='mark_episode'),
    path('upload/', views.vditor_upload, name='vditor_upload'),
    path('enroll/', views.enroll_course, name='enroll_course'),
    path('unenroll/', views.unenroll_course, name='unenroll_course'),
    path('my-courses/', views.my_courses, name='my_courses'),
]

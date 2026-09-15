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
    path('quiz/submit/', views.submit_quiz, name='submit_quiz'),
    path('code/upload/', views.upload_code, name='upload_code'),
    path('code/submit/', views.submit_code, name='submit_code'),
    path('code/history/', views.code_history, name='code_history'),
    path('code/history/<int:history_id>/restore/', views.restore_code_history, name='restore_code_history'),
]

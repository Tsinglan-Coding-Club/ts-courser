from django.urls import path
from . import views

app_name = 'courses'

urlpatterns = [
    path('', views.course_list, name='course_list'),
    path('<int:course_id>/overview/', views.course_overview, name='course_overview'),
    path('<int:course_id>/learn/', views.learning_interface, name='learning_interface'),
    path('<int:course_id>/learn/<int:episode_id>/', views.learning_interface, name='learning_interface_episode'),
]

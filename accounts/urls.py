from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('microsoft/login/', views.microsoft_login, name='microsoft_login'),
    path('microsoft/callback/', views.microsoft_callback, name='microsoft_callback'),
    path(
        'microsoft/select-role/',
        views.microsoft_role_selection,
        name='microsoft_role_selection',
    ),
    path('teacher-pending/', views.teacher_pending, name='teacher_pending'),
    path(
        'first-login/change-credentials/',
        views.first_login_credentials,
        name='first_login_credentials',
    ),
    path('manage/', views.account_management, name='account_management'),
    path(
        'manage/local-students/new/',
        views.create_local_student,
        name='create_local_student',
    ),
    path(
        'manage/teachers/<int:user_id>/approve/',
        views.approve_teacher,
        name='approve_teacher',
    ),
    path('profile/', views.profile_view, name='profile'),
    path('profile/edit/', views.profile_edit, name='profile_edit'),  # Must be before <str:username>
    path('profile/<str:username>/', views.profile_view, name='profile_user'),
    path('api/update-favorite-tags/', views.update_favorite_tags, name='update_favorite_tags'),
]

from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile_view, name='profile'),
    path('profile/edit/', views.profile_edit, name='profile_edit'),  # Must be before <str:username>
    path('profile/<str:username>/', views.profile_view, name='profile_user'),
    path('api/update-favorite-tags/', views.update_favorite_tags, name='update_favorite_tags'),
    path('api/send-verification-code/', views.send_verification_code, name='send_verification_code'),
]

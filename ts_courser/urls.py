"""
URL configuration for ts_courser project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from ts_courser.views import protected_media

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('courses/', include('courses.urls')),
    path('api/', include('progress.urls')),
    path('teacher/', include('teacher.urls')),
    path('protected-media/<path:path>', protected_media, name='protected_media'),
    path('', RedirectView.as_view(url='/courses/', permanent=False)),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

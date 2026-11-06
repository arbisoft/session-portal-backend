"""
URL configuration for arbisoft_sessions_portal project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))

With ``DEBUG`` on, only the directories in ``events.models.PUBLIC_MEDIA_DIRS`` (thumbnails and captions) are
served directly from ``MEDIA_URL``.
Videos and in-flight uploads are deliberately left out: they are streamed by an authenticated view, see
``events.v1.views.VideoAssetStreamView``.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

from events.models import PUBLIC_MEDIA_DIRS


urlpatterns = [
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    path('admin/', admin.site.urls),
    path('api/v1/users/', include('users.v1.urls')),
    path('api/v1/events/', include('events.v1.urls')),
]

if settings.DEBUG:
    for public_dir in PUBLIC_MEDIA_DIRS:
        urlpatterns += static(f'{settings.MEDIA_URL}{public_dir}/', document_root=settings.MEDIA_ROOT / public_dir)

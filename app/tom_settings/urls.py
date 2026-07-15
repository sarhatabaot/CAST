"""django URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.2/topics/http/urls/
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
"""
from django.conf import settings
from django.urls import path, include, re_path
from django.views.generic import TemplateView
from django.views.static import serve


urlpatterns = [
    path('', include('tom_common.urls')),
    path('about/', TemplateView.as_view(template_name='about.html'), name='about'),
    path('candidates/', include('candidates.urls')),
    path('LAST/', include('LAST.urls')),
    path('FP/', include('FP.urls')),
]

# Serve user-uploaded media (cutouts, data products) in production. tom_common.urls
# only wires media serving when DEBUG=True (Django's static() helper returns [] with
# DEBUG=False), which would otherwise 404 every cutout under gunicorn.
urlpatterns += [
    # Fixed 'data/' (not MEDIA_URL): the proxy strips URL_PREFIX, so URL resolution
    # sees the un-prefixed path even when MEDIA_URL carries the prefix for links.
    re_path(r'^data/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]

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
from django.urls import path, include
from django.views.generic import TemplateView

from marshal_tom.views.user_admin import (
    GroupCreateView,
    GroupDeleteView,
    GroupUpdateView,
    UserCreateView,
    UserDeleteView,
    UserListView,
    UserPasswordChangeView,
    UserUpdateView,
)
from marshal_tom.views.inbox import inbox_list, inbox_mark_read, inbox_mark_all_read

urlpatterns = [
    path('users/', UserListView.as_view(), name='user-list'),
    path('users/create/', UserCreateView.as_view(), name='user-create'),
    path('users/<int:pk>/update/', UserUpdateView.as_view(), name='user-update'),
    path('users/<int:pk>/delete/', UserDeleteView.as_view(), name='user-delete'),
    path('users/<int:pk>/changepassword/', UserPasswordChangeView.as_view(), name='admin-user-change-password'),
    path('groups/create/', GroupCreateView.as_view(), name='group-create'),
    path('groups/<int:pk>/update/', GroupUpdateView.as_view(), name='group-update'),
    path('groups/<int:pk>/delete/', GroupDeleteView.as_view(), name='group-delete'),
    path('', include('tom_common.urls')),
    path('about/', TemplateView.as_view(template_name='about.html'), name='about'),
    path('candidates/', include('candidates.urls')),
    path('LAST/', include('LAST.urls')),
    path('FP/', include('FP.urls')),
]

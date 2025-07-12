"""
URL configuration for command_center project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
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

from django.contrib import admin
from django.urls import path
from job_automation_agent.views import ChatbotView

original_get_urls = admin.site.get_urls
def get_urls():
    urls = original_get_urls()
    extra_urls = [
        path("chatbot/", admin.site.admin_view(ChatbotView.as_view(model_admin=None)), name="chatbot"),
    ]
    return extra_urls + urls
admin.site.get_urls = get_urls

urlpatterns = [
    path("admin/", admin.site.urls),
]

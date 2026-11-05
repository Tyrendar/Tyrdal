from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("health/", health),
    path("django-admin/", admin.site.urls),
    path("api/", include("config.api_urls")),
]

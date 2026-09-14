from django.urls import path

from . import views

app_name = "coreprotect"
urlpatterns = [path("", views.index, name="diagnostics")]

from django.urls import path

from . import views

app_name = "auditlog"
urlpatterns = [
    path("audit-log/", views.index, name="index"),
    path("audit-log/<int:pk>/", views.detail, name="detail"),
    path("audit/client-event/", views.client_event, name="client-event"),
]

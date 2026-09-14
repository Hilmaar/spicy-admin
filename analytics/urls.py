from django.urls import path

from .views import diamonds

app_name = "analytics"
urlpatterns = [path("diamonds/", diamonds, name="diamonds")]

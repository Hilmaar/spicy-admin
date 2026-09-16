from django.urls import path

from .ore_config import PAGES
from .views import detail, overview

app_name = "analytics"
urlpatterns = [path("", overview, name="overview")] + [
    path(f"{page.slug}/", detail, {"slug": page.slug}, name=page.slug) for page in PAGES
]

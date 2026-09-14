from django.urls import include, path

urlpatterns = [
    path("auth/", include("accounts.urls")),
    path("docs/", include("documentation.urls")),
    path("diagnostics/", include("coreprotect.urls")),
    path("", include("portal.urls")),
]

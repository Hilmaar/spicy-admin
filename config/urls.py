from django.urls import include, path

urlpatterns = [
    path("", include("auditlog.urls")),
    path("auth/", include("accounts.urls")),
    path("docs/", include("documentation.urls")),
    path("diagnostics/", include("coreprotect.urls")),
    path("ore-statistics/", include("analytics.urls")),
    path("", include("portal.urls")),
]

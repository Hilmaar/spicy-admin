from django.db import models


class EventType(models.TextChoices):
    AUTH_SUCCEEDED = "auth.discord.succeeded", "Authenticated with Discord"
    AUTH_DENIED = "auth.discord.denied", "Discord authentication denied"
    LOGOUT = "auth.logout", "Signed out"
    DASHBOARD = "page.dashboard.viewed", "Viewed Dashboard"
    CODE_OF_CONDUCT = "page.code_of_conduct.viewed", "Viewed Code of Conduct"
    ORE_OVERVIEW = "page.ore_overview.viewed", "Viewed Ore Statistics overview"
    DIAMONDS = "analytics.diamonds.viewed", "Viewed Diamond Statistics"
    ANCIENT_DEBRIS = "analytics.ancient_debris.viewed", "Viewed Ancient Debris Statistics"
    EMERALD = "analytics.emerald.viewed", "Viewed Emerald Statistics"
    FILTERED = "analytics.filtered", "Applied mining filters"
    THRESHOLD_CHANGED = "analytics.threshold_changed", "Changed sample threshold"


class Result(models.TextChoices):
    SUCCESS = "success", "Success"
    DENIED = "denied", "Denied"
    ERROR = "error", "Error"
    INFO = "info", "Info"


ORE_EVENTS = {
    "diamonds": EventType.DIAMONDS,
    "ancient-debris": EventType.ANCIENT_DEBRIS,
    "emerald": EventType.EMERALD,
}

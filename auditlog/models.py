from django.db import models
from django.utils import timezone

from .events import EventType, Result


class AuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("Audit events are append-only.")

    def delete(self):
        raise TypeError("Only retention pruning may delete audit events.")

    def prune_before(self, cutoff):
        return super(AuditQuerySet, self.filter(created_at__lt=cutoff)).delete()


class AuditEvent(models.Model):
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    event_type = models.CharField(max_length=64, choices=EventType.choices)
    result = models.CharField(max_length=8, choices=Result.choices)
    actor_discord_id = models.CharField(max_length=20, null=True)
    actor_display_name = models.CharField(max_length=80, blank=True)
    actor_username = models.CharField(max_length=80, blank=True)
    request_method = models.CharField(max_length=10)
    request_path = models.CharField(max_length=512)
    request_query = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField(null=True)
    user_agent = models.CharField(max_length=512, blank=True)
    referer = models.CharField(max_length=512, blank=True)
    host = models.CharField(max_length=255, blank=True)
    accept_language = models.CharField(max_length=128, blank=True)
    metadata_json = models.JSONField(default=dict)
    objects = AuditQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(fields=("-created_at", "-id"), name="audit_newest"),
            models.Index(fields=("actor_discord_id", "-created_at"), name="audit_actor_time"),
            models.Index(fields=("event_type", "-created_at"), name="audit_event_time"),
            models.Index(fields=("result", "-created_at"), name="audit_result_time"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Audit events are append-only.")
        kwargs["force_insert"] = True
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Only retention pruning may delete audit events.")

    @property
    def actor_name(self):
        return self.actor_display_name or self.actor_username or self.actor_discord_id or "Unknown"

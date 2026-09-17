from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from auditlog.models import AuditEvent


class Command(BaseCommand):
    help = "Delete audit events older than the configured retention (default 365 days)."

    def handle(self, *args, **options):
        days = settings.AUDIT_LOG_RETENTION_DAYS
        if type(days) is not int or days < 1:
            raise CommandError("AUDIT_LOG_RETENTION_DAYS must be a positive integer.")
        count, _ = AuditEvent.objects.prune_before(timezone.now() - timedelta(days=days))
        self.stdout.write(f"Deleted {count} audit events older than {days} days.")

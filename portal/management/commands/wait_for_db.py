import time

from django.core.management.base import BaseCommand, CommandError
from django.db import OperationalError, connection


class Command(BaseCommand):
    help = "Wait briefly for the portal's own PostgreSQL database. Never contacts CoreProtect."

    def handle(self, *args, **options):
        for attempt in range(30):
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                self.stdout.write("Portal database is ready.")
                return
            except OperationalError:
                connection.close()
                if attempt < 29:
                    time.sleep(2)
        raise CommandError("Portal database is unavailable. Check PostgreSQL configuration.")

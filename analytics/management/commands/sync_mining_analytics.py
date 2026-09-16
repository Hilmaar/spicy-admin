from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from coreprotect.repository import CoreProtectUnavailable

from ... import rollup_config as config
from ...sync import SyncBusy, SyncNeedsRebuild, sync_mining


class Command(BaseCommand):
    help = "Backfill/incrementally sync compact mining rollups from read-only CoreProtect."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--full-rebuild", action="store_true")
        mode.add_argument("--reconcile-only", action="store_true")
        parser.add_argument("--batch-size", type=int, default=config.BATCH_SIZE)
        parser.add_argument("--reconcile-hours", type=int, default=config.RECONCILE_HOURS)

    def handle(self, *args, **options):
        try:
            sync_mining(
                full_rebuild=options["full_rebuild"],
                reconcile_only=options["reconcile_only"],
                batch_size=options["batch_size"],
                reconcile_hours=options["reconcile_hours"],
                progress=self.stdout.write,
            )
        except SyncBusy:
            self.stdout.write("Another mining analytics sync is running; no work performed.")
        except (SyncNeedsRebuild, ValueError) as error:
            raise CommandError(str(error)) from None
        except (CoreProtectUnavailable, DatabaseError):
            raise CommandError(
                "Mining analytics sync unavailable; no incomplete batch was committed."
            ) from None

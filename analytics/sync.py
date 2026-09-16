import hashlib
import json
import threading
from contextlib import contextmanager
from datetime import timedelta

from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from coreprotect.repository import get_repository

from . import rollup_config as config
from .models import MiningAnalyticsSyncState, MiningMaterialDaily

_test_lock = threading.Lock()


class SyncBusy(Exception):
    pass


class SyncNeedsRebuild(Exception):
    pass


def material_signature():
    return hashlib.sha256(json.dumps(config.ROLLUP_MATERIALS, sort_keys=True).encode()).hexdigest()


@contextmanager
def sync_lock():
    """Session advisory lock survives batch commits and releases on process/connection exit."""
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [config.LOCK_ID])
            if not cursor.fetchone()[0]:
                raise SyncBusy("Another mining analytics sync is running.")
            try:
                yield
            finally:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [config.LOCK_ID])
    elif connection.vendor == "sqlite":
        # SQLite exists only in the automated/local test environment.
        if not _test_lock.acquire(blocking=False):
            raise SyncBusy("Another mining analytics sync is running.")
        try:
            yield
        finally:
            _test_lock.release()
    else:
        raise SyncNeedsRebuild("Mining sync requires the portal PostgreSQL database.")


def bucket_objects(buckets):
    return [MiningMaterialDaily(**vars(bucket)) for bucket in buckets]


def commit_batch(state, batch):
    with transaction.atomic():
        rows = bucket_objects(batch.buckets)
        existing = {
            (r.date, r.player_uuid, r.world_id, r.material_key): r.break_count
            for r in MiningMaterialDaily.objects.filter(
                date__in={r.date for r in rows},
                material_key__in=config.ROLLUP_MATERIALS,
            )
        }
        for row in rows:
            row.break_count += existing.get(
                (row.date, row.player_uuid, row.world_id, row.material_key), 0
            )
        MiningMaterialDaily.objects.bulk_create(
            rows,
            batch_size=500,
            update_conflicts=True,
            update_fields=["break_count"],
            unique_fields=["date", "player_uuid", "world_id", "material_key"],
        )
        state.last_processed_rowid = batch.through_rowid
        state.generation += 1
        state.save()


def reconciliation_dates(now, hours):
    first = (now - timedelta(hours=hours)).date()
    return tuple(first + timedelta(days=i) for i in range((now.date() - first).days + 1))


def sync_mining(
    *,
    full_rebuild=False,
    reconcile_only=False,
    batch_size=config.BATCH_SIZE,
    reconcile_hours=config.RECONCILE_HOURS,
    progress=lambda message: None,
):
    if full_rebuild and reconcile_only:
        raise ValueError("Choose either full rebuild or reconcile-only.")
    if not 1 <= batch_size <= config.MAX_BATCH_SIZE or not 1 <= reconcile_hours <= 24 * 366:
        raise ValueError("Invalid batch size or reconciliation window.")
    with sync_lock():
        state, _ = MiningAnalyticsSyncState.objects.get_or_create(source_name=config.SOURCE_NAME)
        try:
            signature = material_signature()
            repository = get_repository()
            if full_rebuild:
                high = repository.mining_high_water()
                with transaction.atomic():
                    MiningMaterialDaily.objects.all().delete()
                    state.last_processed_rowid = 0
                    state.backfill_target_rowid = high
                    state.initialized = False
                    state.material_signature = signature
                    state.last_success_at = None
                    state.last_reconciled_at = None
                    state.last_error = ""
                    state.generation += 1
                    state.save()
            if state.material_signature and state.material_signature != signature:
                raise SyncNeedsRebuild("Rollup material configuration changed; run --full-rebuild.")
            if reconcile_only and not state.initialized:
                raise SyncNeedsRebuild("Complete the initial backfill before --reconcile-only.")
            high = repository.mining_high_water()
            minimum_high = state.last_processed_rowid
            if not state.initialized and state.backfill_target_rowid is not None:
                minimum_high = max(minimum_high, state.backfill_target_rowid)
            if high < minimum_high:
                raise SyncNeedsRebuild(
                    "CoreProtect history changed; review source and run --full-rebuild."
                )
            if state.backfill_target_rowid is None:
                state.backfill_target_rowid = high
                state.material_signature = signature
                state.save()
            target = high if state.initialized else state.backfill_target_rowid
            if not reconcile_only:
                while state.last_processed_rowid < target:
                    batch = repository.read_mining_batch(
                        state.last_processed_rowid, target, batch_size, config.ROLLUP_MATERIALS
                    )
                    if not state.last_processed_rowid < batch.through_rowid <= target:
                        raise SyncNeedsRebuild("Invalid source watermark; sync stopped.")
                    commit_batch(state, batch)
                    progress(
                        f"Committed mining batch through row {batch.through_rowid} of {target}."
                    )
            # Rebuild whole UTC buckets against the committed watermark, never beyond it:
            # subsequent incremental batches must not add rows already included by reconciliation.
            dates = reconciliation_dates(timezone.now(), reconcile_hours)
            buckets = []
            for day in dates:
                buckets.extend(
                    repository.read_mining_day(
                        day, state.last_processed_rowid, config.ROLLUP_MATERIALS
                    )
                )
                progress(f"Read reconciliation bucket {day.isoformat()}.")
            with transaction.atomic():
                MiningMaterialDaily.objects.filter(
                    date__in=dates,
                    material_key__in=config.ROLLUP_MATERIALS,
                ).delete()
                MiningMaterialDaily.objects.bulk_create(bucket_objects(buckets), batch_size=500)
                state.initialized = True
                # Reconcile-only must not claim forward ingestion is fresh.
                if not reconcile_only:
                    state.last_success_at = timezone.now()
                state.last_reconciled_at = timezone.now()
                state.last_error = ""
                state.generation += 1
                state.save()
            progress("Mining analytics sync complete.")
        except Exception:
            # Fixed text only: never persist raw database errors, SQL, or credentials.
            MiningAnalyticsSyncState.objects.filter(pk=state.pk).update(
                last_error="Mining analytics sync failed; contact a portal owner.",
                generation=F("generation") + 1,
            )
            raise

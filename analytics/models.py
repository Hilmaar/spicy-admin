from django.db import models


class MiningMaterialDaily(models.Model):
    date = models.DateField()
    player_uuid = models.CharField(max_length=32)
    world_id = models.PositiveIntegerField()
    material_key = models.SlugField(max_length=64)
    break_count = models.PositiveBigIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("date", "player_uuid", "world_id", "material_key"),
                name="mining_daily_identity",
            ),
        ]
        indexes = [
            models.Index(fields=("material_key", "date"), name="mining_material_date"),
            models.Index(
                fields=("world_id", "material_key", "date"), name="mining_world_material_date"
            ),
        ]


class MiningAnalyticsSyncState(models.Model):
    source_name = models.CharField(max_length=64, primary_key=True)
    last_processed_rowid = models.PositiveBigIntegerField(default=0)
    backfill_target_rowid = models.PositiveBigIntegerField(null=True)
    initialized = models.BooleanField(default=False)
    material_signature = models.CharField(max_length=64, default="")
    generation = models.PositiveBigIntegerField(default=0)
    last_success_at = models.DateTimeField(null=True)
    last_reconciled_at = models.DateTimeField(null=True)
    last_error = models.CharField(max_length=160, blank=True)

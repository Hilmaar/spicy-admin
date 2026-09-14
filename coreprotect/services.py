from django.core.cache import cache

from .repository import CoreProtectUnavailable, configured, get_repository


def connection_status():
    if not configured():
        return {"label": "Not configured", "tone": "muted"}
    status = cache.get("coreprotect:connection")
    if status is None:
        try:
            available = get_repository().check_connection()
        except CoreProtectUnavailable:
            available = False
        status = {
            "label": "Connected" if available else "Unavailable",
            "tone": "good" if available else "warning",
        }
        # At most one routine probe per minute per worker. Documentation never probes.
        cache.set("coreprotect:connection", status, timeout=60)
    return status


def diagnostics():
    if not configured():
        return {"available": False, "message": "CoreProtect is not configured."}
    try:
        repository = get_repository()
        version = repository.get_version()
        worlds = repository.list_worlds()
        material = repository.resolve_material("minecraft:diamond_ore")
        return {"available": True, "version": version, "worlds": worlds, "material": material}
    except CoreProtectUnavailable:
        return {
            "available": False,
            "message": "CoreProtect is unavailable. Check the read-only account, host, "
            "network access, table prefix, and database configuration.",
        }

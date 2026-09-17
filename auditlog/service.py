"""Centralized bounded, allowlisted audit writes. Never capture raw payloads/headers."""

import ipaddress
import json
import logging
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.core.exceptions import DisallowedHost, ValidationError
from django.db import DatabaseError, transaction

from analytics.forms import RANGES, UTCDateTimeField
from analytics.ore_config import PAGE_BY_SLUG, PAGES, SAMPLE_OPTIONS

from .events import EventType, Result
from .models import AuditEvent

logger = logging.getLogger(__name__)
_DEFAULT_ACTOR = object()
TABLES = {table.key: page for page in PAGES for table in page.tables}
REASONS = {
    "missing_required_role",
    "not_in_guild",
    "oauth_error",
    "invalid_state",
    "inactive_account",
}


def bounded(value, limit):
    return "".join(c for c in str(value or "")[:limit] if c.isprintable())


def timestamp(value):
    try:
        parsed = UTCDateTimeField().clean(value)
        return parsed.isoformat() if parsed else None
    except ValidationError:
        return None


def thresholds(raw, group=None):
    if isinstance(raw, str):
        if len(raw) > 1024:
            return {}
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    if not isinstance(raw, dict):
        return {}
    return {
        key: value
        for key, value in raw.items()
        if key in TABLES
        and (group is None or TABLES[key].slug == group)
        and type(value) is int
        and value in SAMPLE_OPTIONS
    }


def sanitized_query(query):
    clean = {}
    choices = {"range": dict(RANGES), "event_type": EventType.values, "result": Result.values}
    for key, allowed in choices.items():
        if query.get(key) in allowed:
            clean[key] = query[key]
    for key in ("start", "end"):
        if value := timestamp(query.get(key)):
            clean[key] = value
    actor = query.get("actor", "")
    if actor.isascii() and actor.isdecimal() and len(actor) <= 20:
        clean["actor"] = actor
    for key in ("page", "page_size"):
        value = query.get(key, "")
        if value.isascii() and value.isdecimal() and len(value) <= 8:
            clean[key] = int(value)
    return clean


def metadata_for(event_type, data):
    data = data or {}
    clean = {}
    if data.get("authorization_source") in {"discord_role", "user_override"}:
        clean["authorization_source"] = data["authorization_source"]
    if event_type == EventType.AUTH_DENIED and data.get("reason") in REASONS:
        clean["reason"] = data["reason"]
    group = data.get("material_group")
    if group in PAGE_BY_SLUG:
        clean["material_group"] = group
        clean["configured_world"] = PAGE_BY_SLUG[group].logical_world
        if data.get("range") in dict(RANGES):
            clean["range"] = data["range"]
        for key in ("start", "end"):
            if value := timestamp(data.get(key)):
                clean[key] = value
        clean["thresholds"] = thresholds(data.get("thresholds"), group)
    if event_type == EventType.THRESHOLD_CHANGED and data.get("table") in TABLES:
        clean["table"] = data["table"]
        for key in ("old_threshold", "new_threshold"):
            if type(data.get(key)) is int and data[key] in SAMPLE_OPTIONS:
                clean[key] = data[key]
    return clean


def safe_referer(raw):
    try:
        parts = urlsplit(str(raw)[:2048])
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return ""
        # Retain origin and path only: no credentials, query parameters, or fragments.
        host = parts.hostname
        if ":" in host:
            host = f"[{host}]"
        if parts.port:
            host += f":{parts.port}"
        return bounded(urlunsplit((parts.scheme, host, parts.path, "", "")), 512)
    except ValueError:
        return ""


def client_ip(request):
    def parse(raw):
        try:
            return str(ipaddress.ip_address(raw))
        except ValueError:
            return None

    peer = parse(request.META.get("REMOTE_ADDR", ""))
    trusted = {parse(value) for value in settings.AUDIT_TRUSTED_PROXY_IPS}
    if peer and peer in trusted:
        # The documented Nginx config overwrites XFF with ONE client IP. Reject chains.
        return parse(request.META.get("HTTP_X_FORWARDED_FOR", "")) or peer
    return peer


def record(request, event_type, *, result=Result.SUCCESS, actor=_DEFAULT_ACTOR, metadata=None):
    if event_type not in EventType.values or result not in Result.values:
        raise ValueError("Unsupported audit event.")
    if actor is _DEFAULT_ACTOR:
        actor = request.user if getattr(request.user, "is_authenticated", False) else None
    metadata = dict(metadata or {})
    source = getattr(actor, "_portal_authorization_source", None)
    if source in {"discord_role", "user_override"}:
        metadata["authorization_source"] = source
    try:
        host = request.get_host()
    except DisallowedHost:
        host = ""
    try:
        # Isolate failed inserts with a savepoint, even during an outer auth transaction.
        with transaction.atomic():
            AuditEvent.objects.create(
                event_type=event_type,
                result=result,
                actor_discord_id=bounded(getattr(actor, "discord_id", ""), 20) or None,
                actor_display_name=bounded(getattr(actor, "display_name", ""), 80),
                actor_username=bounded(getattr(actor, "username", ""), 80),
                request_method=bounded(request.method, 10),
                request_path=bounded(request.path, 512),
                request_query=sanitized_query(request.GET),
                ip_address=client_ip(request),
                user_agent=bounded(request.META.get("HTTP_USER_AGENT"), 512),
                referer=safe_referer(request.META.get("HTTP_REFERER", "")),
                host=bounded(host, 255),
                accept_language=bounded(request.META.get("HTTP_ACCEPT_LANGUAGE"), 128),
                metadata_json=metadata_for(event_type, metadata),
            )
        return True
    except DatabaseError:
        logger.error("Audit event could not be recorded.")
        return False

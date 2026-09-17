"""Phase 2B.3 interactions against the existing local synthetic browser fixture."""

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.conf import settings
from django.db import connections
from django.test import Client, RequestFactory
from django.utils import timezone
from playwright.sync_api import expect

from accounts.models import GuildAuthorization, User
from auditlog.events import EventType
from auditlog.models import AuditEvent
from auditlog.service import record


def check_audit_and_scroll(page, base, root, user):
    page.goto(base + "/ore-statistics/diamonds/")
    assert page.locator("#id_world").count() == 0
    for removed in (
        "Queried at",
        "Recent rollback reconciliation",
        "Select both dates",
        "Breaks are filtered",
    ):
        assert removed not in page.locator("main").inner_text()
    for theme in ("dark", "light"):
        if page.locator("html").get_attribute("data-theme") != theme:
            page.get_by_role("button", name=f"Switch to {theme} theme").click()
        for scroll in page.locator(".statistics-scroll").all():
            scroll.evaluate("el => { el.scrollTop = 0; el.scrollLeft = 0; }")
            frame = scroll.locator("..")
            expect(frame).to_have_class("table-scroll-frame more-bottom")
            scroll.evaluate("el => { el.scrollTop = el.scrollHeight; }")
            expect(frame).to_have_class("table-scroll-frame more-top")
            assert (
                scroll.locator("thead th").first.evaluate("el => getComputedStyle(el).position")
                == "sticky"
            )
        page.screenshot(path=str(root / f".artifacts/scroll-fades-{theme}.png"), full_page=True)
    page.set_viewport_size({"width": 320, "height": 700})
    scroll = page.locator(".statistics-scroll").first
    scroll.evaluate("el => { el.scrollTop = 0; el.scrollLeft = 0; }")
    expect(scroll.locator("..")).to_have_class(re.compile(r".*\bmore-right\b.*"))
    assert "more-left" not in scroll.locator("..").get_attribute("class")
    scroll.evaluate("el => { el.scrollLeft = el.scrollWidth; }")
    expect(scroll.locator("..")).to_have_class(re.compile(r".*\bmore-left\b.*"))
    assert "more-right" not in scroll.locator("..").get_attribute("class")
    page.set_viewport_size({"width": 1440, "height": 1080})
    page.goto(base + "/ore-statistics/ancient-debris/")
    expect(page.locator(".table-scroll-frame")).to_have_class("table-scroll-frame")

    # A sort is local only; a threshold change produces one narrow, successful CSRF POST.
    requests = []

    def listener(request):
        if "/audit/client-event/" in request.url:
            requests.append(request)

    page.on("request", listener)
    page.locator("[data-sort=player]").click()
    assert not requests
    select = page.locator("[data-sample-threshold]")
    old = select.input_value()
    new = "500" if old != "500" else "2500"
    with page.expect_response(lambda response: "/audit/client-event/" in response.url) as result:
        select.select_option(new)
    assert result.value.status == 204
    assert requests[-1].post_data_json == {
        "event_type": "analytics.threshold_changed",
        "table": "ancient-debris",
        "old_threshold": int(old),
        "new_threshold": int(new),
    }
    # Simulate failed fetch without adding an intentional network error to the browser console.
    page.evaluate("() => { window.fetch = () => Promise.reject(new Error('fixture offline')); }")
    select.select_option("10000")
    assert (
        page.evaluate("localStorage.getItem('spicy:mining:threshold:v1:ancient-debris')") == "10000"
    )
    page.reload()
    assert select.input_value() == "10000"
    page.remove_listener("request", listener)

    with ThreadPoolExecutor(max_workers=1) as pool:
        staff_cookie = pool.submit(prepare_audit_fixture, user).result()
    page.goto(base + "/audit-log/")
    assert page.get_by_role("heading", name="Audit Log", exact=True).is_visible()
    assert page.locator("#id_range").input_value() == "7d"
    assert page.locator(".audit-table tbody tr").count() == 100
    assert "Audit browser fixture" not in page.locator(".audit-table").inner_text()
    page.get_by_role("link", name="Next", exact=True).click()
    assert page.locator(".audit-table tbody tr").count() == 6
    page.locator("#id_page_size").select_option("50")
    page.locator("#id_actor").select_option(user.discord_id)
    page.locator("#id_event_type").select_option(EventType.DASHBOARD)
    page.get_by_role("button", name="Apply filters").click()
    assert page.locator(".audit-table tbody tr").count() == 50
    page.get_by_role("link", name="Next", exact=True).click()
    assert "page_size=50" in page.url and "actor=" + user.discord_id in page.url
    link = page.locator("[data-audit-detail]").first
    link.focus()
    link.press("Enter")
    dialog = page.locator("#audit-detail-dialog")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("Audit browser fixture")
    expect(dialog).to_contain_text("192.0.2.5")
    for theme in ("light", "dark"):
        page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
        page.screenshot(path=str(root / f".artifacts/audit-detail-{theme}.png"))
    page.keyboard.press("Escape")
    expect(link).to_be_focused()
    page.locator("[data-audit-row]").first.locator("td").first.click()
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Close", exact=True).click()
    page.get_by_role("button", name="Choose custom range").click()
    page.locator("#mining-range-dialog [data-day]").nth(5).click()
    page.locator("#mining-range-dialog [data-day]").nth(6).click()
    page.get_by_text("Adjust precise times (UTC)", exact=True).click()
    page.locator("[data-time-start]").click()
    clock = page.locator("#mining-clock-dialog")
    expect(clock).to_be_visible()
    clock.locator('[data-value="13"]').click()
    clock.locator('[data-value="17"]').click()
    clock.get_by_role("button", name="Use time").click()
    assert page.locator("#start-time-value").inner_text() == "13:17"
    page.locator("#mining-range-dialog").get_by_role("button", name="Cancel", exact=True).click()
    assert page.locator("#id_range").input_value() == "7d"
    page.set_viewport_size({"width": 320, "height": 700})
    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
    page.screenshot(path=str(root / ".artifacts/audit-mobile.png"), full_page=True)
    page.set_viewport_size({"width": 1440, "height": 1080})

    # An actual cached Overlord identity cannot discover or read Admin audit history.
    context = page.context.browser.new_context()
    context.add_cookies(
        [
            {
                "name": settings.SESSION_COOKIE_NAME,
                "value": staff_cookie,
                "url": base,
            }
        ]
    )
    staff_page = context.new_page()
    staff_page.goto(base + "/")
    assert staff_page.get_by_role("link", name="Audit Log", exact=True).count() == 0
    assert staff_page.goto(base + "/audit-log/").status == 403
    context.close()


def prepare_audit_fixture(user):
    """Keep Django database work outside Playwright's event-loop thread."""
    try:
        # Seed history only in the harness's disposable SQLite database.
        AuditEvent.objects.prune_before(timezone.now() + timedelta(days=1))
        request = RequestFactory().get(
            "/", HTTP_USER_AGENT="Audit browser fixture", REMOTE_ADDR="192.0.2.5"
        )
        request.user = user
        for _ in range(106):
            record(request, EventType.DASHBOARD)
        staff, _ = User.objects.get_or_create(
            discord_id="987654321", defaults={"username": "Staff fixture"}
        )
        GuildAuthorization.objects.update_or_create(
            user=staff,
            defaults={
                "guild_id": settings.DISCORD_GUILD_ID,
                "roles": [settings.DISCORD_OVERLORD_ROLE_ID],
                "is_member": True,
                "unavailable": False,
                "checked_at": timezone.now(),
            },
        )
        client = Client()
        client.force_login(staff, backend="accounts.backends.DiscordSessionBackend")
        return client.cookies[settings.SESSION_COOKIE_NAME].value
    finally:
        connections.close_all()

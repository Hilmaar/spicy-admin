"""Optional local browser regression: requires Playwright and installed Microsoft Edge.

Run with the project Python from the repository root. Uses dummy test settings, a
loopback-only server, mocked external services, and .artifacts/ui.sqlite3; never production.
"""

# ruff: noqa: E402
import os
import sys
import threading
from pathlib import Path
from unittest.mock import patch
from wsgiref.simple_server import WSGIRequestHandler, make_server

ROOT = Path(__file__).resolve().parent.parent
(ROOT / ".artifacts").mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT))
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.test"
import django
from django.conf import settings

settings.DATABASES["default"]["NAME"] = str(ROOT / ".artifacts" / "ui.sqlite3")
django.setup()
from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.core.management import call_command
from django.core.wsgi import get_wsgi_application
from django.test import Client
from playwright.sync_api import sync_playwright

from accounts.discord import Membership
from accounts.models import User
from coreprotect.mining import DiamondStatsRow, MaterialBreakRow
from coreprotect.repository import World

call_command("migrate", verbosity=0)
from analytics.models import MiningAnalyticsSyncState, MiningMaterialDaily
from analytics.test_rollups import ready_state

MiningAnalyticsSyncState.objects.all().delete()
MiningMaterialDaily.objects.all().delete()
ready_state()
for uuid, counts in [("a" * 32, (123000, 567000)), ("b" * 32, (10, 20))]:
    for key, count in zip(("stone", "deepslate"), counts, strict=True):
        MiningMaterialDaily.objects.create(
            date="2026-09-01", player_uuid=uuid, world_id=927, material_key=key, break_count=count
        )

user, _ = User.objects.get_or_create(
    discord_id="123456789",
    defaults={
        "username": "Reviewer",
        "display_name": "Staff preview",
    },
)
user.set_unusable_password()
user.save()
client = Client()
client.force_login(user, backend="accounts.backends.DiscordSessionBackend")

fallback_client = Client()
fallback_client.force_login(user, backend="accounts.backends.DiscordSessionBackend")


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass


server = make_server(
    "127.0.0.1", 0, StaticFilesHandler(get_wsgi_application()), handler_class=QuietHandler
)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
base = f"http://127.0.0.1:{server.server_port}"
errors = []
try:
    with (
        patch("accounts.permissions.fetch_membership", return_value=Membership(True, ("200",))),
        patch("analytics.services.get_repository") as analytics_factory,
    ):
        analytics_factory.return_value.list_worlds.return_value = [
            World(83, "world"),
            World(927, "resource_world"),
        ]
        analytics_factory.return_value.get_diamond_stats.return_value = (
            DiamondStatsRow("a" * 32, "FixtureAlice", 1234, 5678),
            DiamondStatsRow("b" * 32, "FixtureBob", 101, 202),
            *(DiamondStatsRow(f"{i:032x}", f"Miner{i:03}", 1, 1) for i in range(1, 51)),
        )
        analytics_factory.return_value.get_denominator_stats.return_value = (
            MaterialBreakRow("a" * 32, "FixtureAlice", (123000, 567000)),
            MaterialBreakRow("b" * 32, "FixtureBob", (10, 20)),
            MaterialBreakRow("f" * 32, "DenominatorOnly", (999, 999)),
            *(MaterialBreakRow(f"{i:032x}", f"Miner{i:03}", (1500, 2500)) for i in range(1, 51)),
        )
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 1080},
                timezone_id="Pacific/Honolulu",
                has_touch=True,
            )
            context.route(
                "https://cdn.discordapp.com/**",
                lambda route: route.fulfill(
                    content_type="image/svg+xml",
                    body=(ROOT / "static/favicon.svg").read_text(),
                ),
            )
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: errors.append(message.text) if message.type == "error" else None,
            )
            page.goto(base + "/auth/login/")
            assert page.locator("html").get_attribute("data-theme") == "dark"
            page.screenshot(path=str(ROOT / ".artifacts/login-dark.png"), full_page=True)
            context.add_cookies(
                [
                    {
                        "name": settings.SESSION_COOKIE_NAME,
                        "value": client.cookies[settings.SESSION_COOKIE_NAME].value,
                        "url": base,
                    }
                ]
            )
            page.goto(base + "/")
            assert page.get_by_role("heading", name="Dashboard", exact=True).is_visible()
            assert "Staff preview" in page.locator(".profile").inner_text()
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
            page.screenshot(path=str(ROOT / ".artifacts/dashboard-dark.png"), full_page=True)
            page.get_by_role("button", name="Switch to light theme").click()
            page.reload()
            assert page.locator("html").get_attribute("data-theme") == "light"
            page.screenshot(path=str(ROOT / ".artifacts/dashboard-light.png"), full_page=True)
            page.get_by_role("link", name="Admin Cheat Sheet", exact=True).click()
            assert page.locator("table").is_visible()
            page.screenshot(path=str(ROOT / ".artifacts/docs-light.png"), full_page=True)
            page.get_by_role("button", name="Switch to dark theme").click()
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(base + "/")
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
            assert not page.get_by_role("link", name="Dashboard", exact=True).is_visible()
            page.get_by_role("button", name="Open navigation").click()
            page.get_by_role("link", name="Dashboard", exact=True).wait_for(state="visible")
            page.screenshot(
                path=str(ROOT / ".artifacts/mobile-menu.png"), full_page=True, animations="disabled"
            )
            page.keyboard.press("Escape")
            assert (
                page.get_by_role("button", name="Open navigation").get_attribute("aria-expanded")
                == "false"
            )
            page.locator("#sidebar").wait_for(state="hidden")
            page.screenshot(path=str(ROOT / ".artifacts/dashboard-mobile.png"), full_page=True)
            page.goto(base + "/docs/admin-cheat-sheet/")
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
            page.goto(base + "/diagnostics/")
            assert page.get_by_role("heading", name="Connection unavailable").is_visible()
            page.set_viewport_size({"width": 1440, "height": 1080})
            page.get_by_role("link", name="Ore Statistics", exact=True).click()
            assert page.url.endswith("/ore-statistics/diamonds/")
            assert page.get_by_role("heading", name="Diamond Mining Statistics").is_visible()
            assert (
                page.locator("#normal-diamonds")
                .get_by_role("cell", name="1,234", exact=True)
                .is_visible()
            )
            assert (
                page.locator("#deepslate-diamonds")
                .get_by_role("cell", name="5,678", exact=True)
                .is_visible()
            )
            assert page.locator(".statistics-table").count() == 2
            assert page.locator("#normal-diamonds thead th").count() == 5
            assert page.locator("#deepslate-diamonds thead th").count() == 5
            analytics_factory.return_value.get_denominator_stats.assert_not_called()
            assert page.get_by_text("DenominatorOnly", exact=True).count() == 0
            assert page.locator("#id_range").input_value() == "all"
            page.screenshot(path=str(ROOT / ".artifacts/diamonds-dark.png"), full_page=True)
            page.get_by_role("button", name="Switch to light theme").click()
            page.screenshot(path=str(ROOT / ".artifacts/diamonds-light.png"), full_page=True)
            page.get_by_label("Time range", exact=True).select_option("7d")
            page.get_by_label("World", exact=True).select_option("927")
            page.get_by_role("button", name="Apply filters").click()
            assert page.get_by_role("heading", name="Last 7 days · resource_world").is_visible()
            # Whole dates, preview, two months, no query before Apply, and Cancel.
            before_url = page.url
            page.get_by_role("button", name="Choose custom range").click()
            dialog = page.locator("#mining-range-dialog")
            assert dialog.locator(".calendar-month").count() == 2
            # Seed dates through the public GET interface; clock is the normal precise UI.
            page.keyboard.press("Escape")
            page.goto(
                base + "/ore-statistics/diamonds/?range=custom&world=927"
                "&start=2026-09-01T12:00:00Z&end=2026-09-02T12:00:00Z"
            )
            page.get_by_role("button", name="Choose custom range").click()
            dialog.get_by_role("button", name="2026-09-10", exact=True).click()
            dialog.get_by_role("button", name="2026-09-12", exact=True).hover()
            assert dialog.locator('[data-day="2026-09-11"]').evaluate(
                "el => el.classList.contains('range-preview')"
            )
            dialog.get_by_role("button", name="2026-09-12", exact=True).click()
            assert page.locator("#id_end").input_value() == "2026-09-02T12:00:00Z"
            page.screenshot(path=str(ROOT / ".artifacts/range-light.png"))
            page.get_by_role("button", name="Apply range", exact=True).click()
            assert page.locator("#id_start").input_value() == "2026-09-10T00:00:00Z"
            assert page.locator("#id_end").input_value() == "2026-09-13T00:00:00Z"
            query = analytics_factory.return_value.get_diamond_stats.call_args.args[0]
            assert query.start.isoformat() == "2026-09-10T00:00:00+00:00"
            assert query.end.isoformat() == "2026-09-13T00:00:00+00:00"
            before_url = page.url
            before_calls = analytics_factory.return_value.get_denominator_stats.call_count
            page.get_by_role("button", name="Choose custom range").click()
            dialog.get_by_role("button", name="2026-09-15", exact=True).click()
            page.keyboard.press("ArrowRight")
            assert page.locator(":focus").get_attribute("data-day") == "2026-09-16"
            page.keyboard.press("Enter")
            page.keyboard.press("Escape")
            assert not dialog.is_visible()
            assert page.url == before_url
            assert analytics_factory.return_value.get_denominator_stats.call_count == before_calls
            assert page.get_by_role("button", name="Choose custom range").evaluate(
                "el => el === document.activeElement"
            )
            # Clock changes are local drafts, and each Cancel preserves prior values.
            page.get_by_role("button", name="Choose custom range").click()
            page.get_by_text("Adjust precise times (UTC)", exact=True).click()
            assert not page.locator("#precise-start").is_visible()
            assert not page.locator("#precise-end").is_visible()
            assert page.locator("#start-time-value").inner_text() == "00:00"
            assert page.locator("#end-time-value").inner_text() == "23:59"
            clock = page.locator("#mining-clock-dialog")
            start_button = page.locator("[data-time-start]")
            end_button = page.locator("[data-time-end]")
            start_button.click()
            assert clock.locator(".clock-number").count() == 24
            page.screenshot(path=str(ROOT / ".artifacts/clock-hours-light.png"))
            clock.locator('[data-value="13"]').click()
            assert clock.locator(".clock-number").count() == 60
            clock.locator('[data-value="17"]').click()
            clock.get_by_role("button", name="Cancel", exact=True).click()
            assert page.locator("#start-time-value").inner_text() == "00:00"
            assert start_button.evaluate("el => el === document.activeElement")
            start_button.click()
            clock.locator('[data-value="13"]').click()
            clock.locator('[data-value="17"]').click()
            page.screenshot(path=str(ROOT / ".artifacts/clock-minutes-light.png"))
            clock.get_by_role("button", name="Use time").click()
            assert page.locator("#precise-start").input_value() == "2026-09-10T13:17:00Z"
            assert page.locator("#id_start").input_value() == "2026-09-10T00:00:00Z"
            assert analytics_factory.return_value.get_denominator_stats.call_count == before_calls
            # Keyboard: inner 00 -> 23 -> minutes -> 59, Escape cancels only the clock.
            end_button.click()
            face = clock.get_by_role("slider")
            face.press("Home")
            face.press("ArrowLeft")
            assert face.get_attribute("aria-valuenow") == "23"
            face.press("Enter")
            face.press("End")
            assert face.get_attribute("aria-valuenow") == "59"
            page.keyboard.press("Escape")
            assert dialog.is_visible() and not clock.is_visible()
            assert page.locator("#precise-end").input_value() == "2026-09-13T00:00:00Z"
            # Explicit 23:59 is exclusive; end-of-day restores next midnight.
            end_button.click()
            clock.locator('[data-value="23"]').click()
            clock.locator('[data-value="59"]').click()
            clock.get_by_role("button", name="Use time").click()
            assert page.locator("#precise-end").input_value() == "2026-09-12T23:59:00Z"
            page.get_by_role("button", name="Use end of day").click()
            assert page.locator("#precise-end").input_value() == "2026-09-13T00:00:00Z"
            page.get_by_role("button", name="Apply range", exact=True).click()
            assert (
                analytics_factory.return_value.get_denominator_stats.call_args.args[0].start.hour
                == 13
            )
            assert (
                analytics_factory.return_value.get_denominator_stats.call_args.args[0].start.minute
                == 17
            )
            page.get_by_role("button", name="Choose custom range").click()
            page.get_by_text("Adjust precise times (UTC)", exact=True).click()
            start_button.click()
            clock.locator('[data-value="12"]').click()
            clock.locator('[data-value="5"]').click()
            clock.get_by_role("button", name="Use time").click()
            dialog.get_by_role("button", name="Cancel", exact=True).click()
            assert page.locator("#id_start").input_value() == "2026-09-10T13:17:00Z"
            # A single leap day includes all of February 29 in a non-UTC browser timezone.
            page.goto(
                base + "/ore-statistics/diamonds/?range=custom&world=927"
                "&start=2024-02-29T00:00:00Z&end=2024-03-01T00:00:00Z"
            )
            page.get_by_role("button", name="Choose custom range").click()
            dialog.get_by_role("button", name="2024-02-29", exact=True).click()
            dialog.get_by_role("button", name="2024-02-29", exact=True).click()
            page.get_by_role("button", name="Apply range", exact=True).click()
            assert page.locator("#id_end").input_value() == "2024-03-01T00:00:00Z"
            # Reverse selection spanning two months normalizes the endpoints.
            page.get_by_role("button", name="Choose custom range").click()
            dialog.get_by_role("button", name="2024-03-02", exact=True).click()
            dialog.get_by_role("button", name="2024-02-28", exact=True).click()
            page.get_by_role("button", name="Apply range", exact=True).click()
            assert page.locator("#id_start").input_value() == "2024-02-28T00:00:00Z"
            assert page.locator("#id_end").input_value() == "2024-03-03T00:00:00Z"
            # Existing offset/subsecond bounds survive opening and applying the clock UI unchanged.
            page.goto(
                base + "/ore-statistics/diamonds/?range=custom&world=927"
                "&start=2026-09-10T02:00:00.000001%2B02:00"
                "&end=2026-09-10T02:00:00.000002%2B02:00"
            )
            page.get_by_role("button", name="Choose custom range").click()
            page.get_by_role("button", name="Apply range", exact=True).click()
            precise_query = analytics_factory.return_value.get_denominator_stats.call_args.args[0]
            assert precise_query.start.isoformat() == "2026-09-10T00:00:00.000001+00:00"
            assert precise_query.end.isoformat() == "2026-09-10T00:00:00.000002+00:00"
            # Sticky headers hold their position while the long table scrolls.
            for scroll in page.locator(".statistics-scroll").all():
                scroll.scroll_into_view_if_needed()
                head = scroll.locator("thead th").first
                top = head.bounding_box()["y"]
                scroll.evaluate("el => { el.scrollTop = 500; }")
                assert abs(head.bounding_box()["y"] - top) < 2
                assert head.evaluate("el => getComputedStyle(el).position") == "sticky"
                assert not scroll.evaluate("el => el.scrollWidth > el.clientWidth")
                scroll.evaluate("el => { el.scrollTop = 0; }")
            assert page.get_by_role("heading", name="Custom range · resource_world").is_visible()
            page.get_by_role("button", name="Switch to dark theme").click()
            page.set_viewport_size({"width": 390, "height": 844})
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
            page.locator("#sidebar").wait_for(state="hidden")
            page.screenshot(path=str(ROOT / ".artifacts/diamonds-mobile.png"), full_page=True)
            page.set_viewport_size({"width": 320, "height": 700})
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
            assert page.locator(".statistics-scroll").first.evaluate(
                "el => el.scrollWidth > el.clientWidth"
            )
            page.get_by_role("button", name="Choose custom range").click()
            assert dialog.locator(".calendar-month").count() == 1
            assert not dialog.evaluate("el => el.scrollWidth > el.clientWidth")
            page.screenshot(path=str(ROOT / ".artifacts/range-mobile.png"))
            page.get_by_text("Adjust precise times (UTC)", exact=True).click()
            start_button.click()
            assert not clock.evaluate("el => el.scrollWidth > el.clientWidth")
            page.screenshot(path=str(ROOT / ".artifacts/clock-mobile-dark.png"))
            # Touch-select inner midnight and an arbitrary minute between five-minute labels.
            import math

            box = clock.locator(".clock-face").bounding_box()
            center_x = box["x"] + box["width"] / 2
            center_y = box["y"] + box["height"] / 2
            page.touchscreen.tap(center_x, center_y - box["width"] * 76 / 280)
            assert clock.get_by_role("slider").get_attribute("aria-label") == "Minute"
            angle = 37 * math.pi / 30
            radius = box["width"] * 108 / 280
            page.touchscreen.tap(
                center_x + math.sin(angle) * radius, center_y - math.cos(angle) * radius
            )
            assert clock.get_by_role("slider").get_attribute("aria-valuenow") == "37"
            page.screenshot(path=str(ROOT / ".artifacts/clock-minutes-dark.png"))
            page.keyboard.press("Escape")
            page.keyboard.press("Escape")
            page.set_viewport_size({"width": 1440, "height": 1080})
            page.get_by_role("button", name="Choose custom range").click()
            page.screenshot(path=str(ROOT / ".artifacts/range-dark.png"))
            page.keyboard.press("Escape")
            from analytics.rollups import RollupUnavailable

            with patch(
                "analytics.services.rollups.read_snapshot",
                side_effect=RollupUnavailable(
                    "Base-block analytics are initializing. "
                    "A portal owner must complete the mining sync."
                ),
            ):
                response = page.goto(base + "/ore-statistics/diamonds/")
                assert response.status == 503
                assert page.get_by_role(
                    "heading", name="Base-block analytics unavailable"
                ).is_visible()
                assert page.locator(".statistics-table").count() == 0
                page.screenshot(path=str(ROOT / ".artifacts/rollup-not-ready.png"), full_page=True)
            errors[:] = [error for error in errors if "503" not in error]
            page.get_by_role("button", name="Sign out").click()
            assert page.url.endswith("/auth/login/")
            fallback = browser.new_context(java_script_enabled=False)
            fallback.add_cookies(
                [
                    {
                        "name": settings.SESSION_COOKIE_NAME,
                        "value": fallback_client.cookies[settings.SESSION_COOKIE_NAME].value,
                        "url": base,
                    }
                ]
            )
            fallback_page = fallback.new_page()
            fallback_page.goto(base + "/ore-statistics/diamonds/")
            assert fallback_page.get_by_label("Start (UTC)", exact=True).is_visible()
            fallback_page.get_by_label("Time range", exact=True).select_option("custom")
            fallback_page.get_by_label("Start (UTC)", exact=True).fill("2026-09-10T00:00:00Z")
            fallback_page.get_by_label("End (UTC, exclusive)", exact=True).fill(
                "2026-09-13T00:00:00Z"
            )
            fallback_page.get_by_role("button", name="Apply filters").click()
            assert fallback_page.get_by_role(
                "heading", name="Custom range", exact=False
            ).is_visible()
            fallback.close()
            browser.close()
            assert not errors, errors
            print(
                "Browser checks passed: Phase 1; separate mining tables; rollup bootstrap; "
                "UTC calendar and radial clock; keyboard/touch/Cancel; dark/light; mobile; "
                "sticky headers; no JS errors."
            )
finally:
    server.shutdown()

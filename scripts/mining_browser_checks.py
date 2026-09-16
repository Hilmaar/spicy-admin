"""Phase 2B.2 browser assertions, run by check_browser.py with local synthetic data."""

from fractions import Fraction
from functools import cmp_to_key


def check_mining_tables(page, base, repository, root):
    assert page.locator(".statistics-table").first.get_attribute("id") == "deepslate-diamonds"
    headers = page.locator("#normal-diamonds thead th")
    assert headers.nth(3).get_attribute("aria-sort") == "descending"
    normal = page.locator('[data-table-key="normal-diamonds"]')
    deep = page.locator('[data-table-key="deepslate-diamonds"]')
    select = normal.locator("select")
    assert select.locator("option").evaluate_all("els => els.map(el => el.value)") == [
        "250",
        "500",
        "1000",
        "2500",
        "5000",
        "10000",
    ]
    assert select.input_value() == deep.locator("select").input_value() == "1000"
    original = normal.locator("tbody tr").evaluate_all(
        "els => els.map(el => ({...el.dataset, "
        "cells: [...el.querySelectorAll('td')].map(c => c.textContent)}))"
    )
    original_cells = {r["uuid"]: r["cells"] for r in original}
    target_calls = repository.get_diamond_stats.call_count
    base_calls = repository.get_denominator_stats.call_count

    def expected(column, direction, threshold):
        def value(row):
            target, count = int(row["target"]), int(row["base"])
            return {
                "player": row["player"].lower(),
                "target": target,
                "base": count,
                "rate": Fraction(target, count) if count else None,
                "inverse": Fraction(count, target) if target else None,
            }[column]

        def compare(a, b):
            small_a, small_b = int(a["base"]) < threshold, int(b["base"]) < threshold
            if small_a != small_b:
                return 1 if small_a else -1
            va, vb = value(a), value(b)
            if (va is None) != (vb is None):
                return 1 if va is None else -1
            if va != vb:
                result = -1 if va < vb else 1
                return result if direction == "ascending" else -result
            ta = (a["player"].lower(), a["player"], a["uuid"])
            tb = (b["player"].lower(), b["player"], b["uuid"])
            return (ta > tb) - (ta < tb)

        return [r["uuid"] for r in sorted(original, key=cmp_to_key(compare))]

    def assert_order(column, direction, threshold):
        actual = normal.locator("tbody tr").evaluate_all("els => els.map(el => el.dataset.uuid)")
        assert actual == expected(column, direction, threshold), (column, direction, threshold)
        assert (
            normal.locator(f'[data-sort="{column}"]').locator("..").get_attribute("aria-sort")
            == direction
        )
        assert normal.locator('thead th:not([aria-sort="none"])').count() == 1
        for row in normal.locator("tbody tr").all():
            small = int(row.get_attribute("data-base")) < threshold
            assert row.locator(".sample-badge").is_visible() == small
            assert (
                row.locator("[data-ratio]").first.evaluate(
                    "el => el.classList.contains('ratio-muted')"
                )
                == small
            )

    assert_order("rate", "descending", 1000)
    # Every direction/column preserves small-sample-last and deterministic ties/missing ratios.
    for column in ("player", "target", "base", "rate", "inverse"):
        button = normal.locator(f'[data-sort="{column}"]')
        button.focus()
        button.press("Enter")
        direction = button.locator("..").get_attribute("aria-sort")
        assert_order(column, direction, 1000)
        button.press("Space")
        reverse = "ascending" if direction == "descending" else "descending"
        assert_order(column, reverse, 1000)
    select.select_option("2500")
    assert_order(column, reverse, 2500)
    assert deep.locator("select").input_value() == "1000"
    current = normal.locator("tbody tr").evaluate_all(
        "els => els.map(el => [el.dataset.uuid, "
        "[...el.querySelectorAll('td')].map(c => c.textContent)])"
    )
    assert dict(current) == original_cells
    assert repository.get_diamond_stats.call_count == target_calls
    assert repository.get_denominator_stats.call_count == base_calls
    deep.locator("select").select_option("5000")
    page.reload()
    assert normal.locator("select").input_value() == "2500"
    assert deep.locator("select").input_value() == "5000"
    assert_order("rate", "descending", 2500)

    nav = page.get_by_role("navigation", name="Ore materials")
    nav.get_by_role("link", name="Ancient Debris", exact=True).click()
    page.wait_for_load_state()
    assert page.url.endswith("/ore-statistics/ancient-debris/")
    assert page.locator(".statistics-table").count() == 1
    assert page.locator("#ancient-debris-threshold").input_value() == "1000"
    page.locator("#ancient-debris-threshold").select_option("5000")
    page.screenshot(path=str(root / ".artifacts/debris-dark.png"), full_page=True)
    nav.get_by_role("link", name="Emerald", exact=True).click()
    page.wait_for_load_state()
    assert page.locator(".statistics-table").first.get_attribute("id") == "deepslate-emerald"
    assert page.locator("#normal-emerald-threshold").input_value() == "1000"
    page.locator("#normal-emerald-threshold").select_option("500")
    assert page.locator("#deepslate-emerald-threshold").input_value() == "1000"
    page.get_by_role("button", name="Switch to light theme").click()
    page.screenshot(path=str(root / ".artifacts/emerald-light.png"), full_page=True)
    page.set_viewport_size({"width": 320, "height": 700})
    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
    nav.get_by_role("link", name="Overview", exact=True).click()
    page.wait_for_load_state()
    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
    page.screenshot(path=str(root / ".artifacts/overview-mobile.png"), full_page=True)
    page.set_viewport_size({"width": 1440, "height": 1080})
    nav.get_by_role("link", name="Ancient Debris", exact=True).click()
    page.wait_for_load_state()
    assert page.locator("#ancient-debris-threshold").input_value() == "5000"
    nav.get_by_role("link", name="Emerald", exact=True).click()
    page.wait_for_load_state()
    assert page.locator("#normal-emerald-threshold").input_value() == "500"
    nav.get_by_role("link", name="Diamonds", exact=True).click()
    page.wait_for_load_state()
    assert normal.locator("select").input_value() == "2500"
    assert deep.locator("select").input_value() == "5000"
    page.get_by_role("button", name="Switch to dark theme").click()
    # Invalid preferences safely fall back to the server-configured per-table default.
    page.evaluate("localStorage.setItem('spicy:mining:threshold:v1:normal-diamonds', '999')")
    page.reload()
    assert normal.locator("select").input_value() == "1000"
    deep.locator("select").select_option("1000")
    repository.get_denominator_stats.assert_not_called()
    # Storage denied must not disable sorting, threshold changes, or the page.
    page.evaluate("() => { Storage.prototype.setItem = () => { throw new Error('blocked'); }; }")
    normal.locator("select").select_option("500")
    assert normal.locator("select").input_value() == "500"
    page.goto(base + "/ore-statistics/diamonds/")

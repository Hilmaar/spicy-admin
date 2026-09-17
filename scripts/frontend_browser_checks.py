"""Native controls, initial overflow, CSS-only state and CSP in Edge and Firefox."""

import re

from playwright.sync_api import expect


def install_csp_monitor(context, violations):
    context.expose_binding("reportCspViolation", lambda source, value: violations.append(value))
    context.add_init_script("""document.addEventListener('securitypolicyviolation', event => {
      window.reportCspViolation({directive: event.effectiveDirective, blocked: event.blockedURI,
        source: event.sourceFile});
    });""")


def check_frontend_polish(page, base, root, browser_name):
    # Fresh navigation, no programmatic scroll/event before checking initial edge state.
    page.goto(base + "/ore-statistics/diamonds/")
    for frame in page.locator(".table-scroll-frame").all():
        expect(frame).to_have_class("table-scroll-frame more-bottom")
        assert frame.locator(".statistics-scroll").evaluate("el => el.scrollTop") == 0
        assert (
            frame.locator(".scroll-edge-bottom").evaluate("el => getComputedStyle(el).opacity")
            == "1"
        )
        assert (
            frame.locator(".scroll-edge-bottom").evaluate("el => getComputedStyle(el).height")
            == "44px"
        )
        assert (
            frame.locator(".scroll-edge-top").evaluate("el => getComputedStyle(el).height")
            == "10px"
        )
        assert (
            frame.locator(".scroll-edge-top").evaluate("el => getComputedStyle(el).opacity") == "0"
        )
    scroll = page.locator(".statistics-scroll").first
    frame = scroll.locator("..")
    scroll.evaluate("el => { el.scrollTop = el.scrollHeight; }")
    expect(frame).to_have_class("table-scroll-frame more-top")
    scroll.evaluate("el => { el.scrollTop -= 50; }")
    expect(frame).to_have_class(re.compile(r".*more-bottom.*"))
    assert (
        float(frame.locator(".scroll-edge-top").evaluate("el => getComputedStyle(el).opacity"))
        < 0.8
    )
    # Row content changes, without any scroll, recompute no-overflow state.
    scroll.evaluate(
        "el => el.querySelectorAll('tbody tr').forEach((row, i) => { if (i) row.remove(); })"
    )
    expect(frame).to_have_class("table-scroll-frame")
    page.reload()
    for theme in ("dark", "light"):
        if page.locator("html").get_attribute("data-theme") != theme:
            page.get_by_role("button", name=f"Switch to {theme} theme").click()
        for select in page.locator("select").all():
            select.hover()
            style = select.evaluate("""el => { const s = getComputedStyle(el); return {
                appearance: s.appearance, background: s.backgroundColor,
                expected: s.getPropertyValue('--surface-raised').trim(),
                clip: s.backgroundClip, image: s.backgroundImage}; }""")
            assert style["appearance"] == "none"
            assert style["clip"] == "border-box"
            assert "select-chevron" in style["image"]
            # Computed color must paint the element, not a text-width inner label.
            assert style["background"] in ("rgb(48, 51, 48)", "rgb(234, 240, 236)")
            select.focus()
            select.press("ArrowDown")
            select.press("Escape")
            page.keyboard.press("Tab")
            page.keyboard.press("Shift+Tab")
            assert select.evaluate("el => getComputedStyle(el).outlineStyle") != "none"
        page.mouse.move(0, 0)
        assert scroll.evaluate("el => getComputedStyle(el).scrollbarColor").startswith(
            "rgb(0, 251, 154)"
        )
        page.screenshot(
            path=str(root / f".artifacts/polish-{browser_name}-{theme}.png"), full_page=True
        )
    # Reset preferences changed by keyboard checks before the existing sorting oracle runs.
    page.evaluate("""() => { for (const key of Object.keys(localStorage)) {
        if (key.startsWith('spicy:mining:threshold:')) localStorage.removeItem(key);
    } }""")
    page.goto(base + "/audit-log/")
    for select in page.locator("select").all():
        select.hover()
        assert select.evaluate("el => getComputedStyle(el).appearance") == "none"
        assert select.evaluate("el => getComputedStyle(el).backgroundColor") == "rgb(234, 240, 236)"
    assert page.locator("[style], script:not([src]), [onclick], style").count() == 0
    page.goto(base + "/ore-statistics/diamonds/")
    page.get_by_role("button", name="Switch to dark theme").click()

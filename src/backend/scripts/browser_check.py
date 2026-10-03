# ruff: noqa: B023  (each check runs inside its own loop iteration)
"""Real-browser checks of the storefront JavaScript at phone size, in English and Arabic.

Needs the app running on localhost:8000 with the demo catalog (python -m scripts.seed):

    uv run --with playwright python -m playwright install chromium   # once
    uv run --with playwright python -m scripts.browser_check
"""

import os

from playwright.sync_api import expect, sync_playwright

B = os.environ.get("BASE_URL_CHECK", "http://localhost:8000")
results: list[tuple[str, bool, str]] = []


def check(name: str, fn) -> None:  # type: ignore[no-untyped-def]
    try:
        fn()
        results.append((name, True, ""))
    except Exception as exc:
        results.append((name, False, str(exc).splitlines()[0][:160]))


with sync_playwright() as p:
    browser = p.chromium.launch()
    for prefix in ("", "/ar"):
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True)
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        tag = prefix or "/en"

        def mobile_menu() -> None:
            page.goto(B + prefix + "/")
            page.locator("button[aria-controls='mobile-nav']").click()
            expect(page.locator("#mobile-nav")).to_be_visible()
            page.locator("#mobile-nav button[data-hs-overlay]").click()
            expect(page.locator("#mobile-nav")).to_be_hidden()

        def picker() -> None:
            page.goto(B + prefix + "/p/essential-cotton-tee")
            add = page.locator("[data-add-button]")
            page.locator("label:has(input[data-color])").nth(1).click()  # Black
            expect(page.locator("[data-color-name]")).not_to_be_empty()
            # XL has stock 2 -> low-stock message
            page.locator("label:has(input[data-size])").nth(3).click()
            expect(page.locator("[data-stock]")).to_contain_text("2")
            expect(add).to_be_enabled()
            # Gallery shows only Black photos (+ shared)
            hidden = page.locator("[data-gallery] figure.hidden").count()
            assert hidden == 2, f"expected 2 hidden white photos, got {hidden}"

        def add_and_drawer() -> None:
            page.locator("label:has(input[data-size])").nth(1).click()  # M
            page.locator("[data-add-button]").click()
            expect(page.locator("#cart-drawer")).to_be_visible()
            expect(page.locator("#toasts")).not_to_be_empty()
            expect(page.locator("#cart-badge")).to_contain_text("1")

        def stepper_and_remove() -> None:
            drawer = page.locator("#cart-drawer-body")
            drawer.locator("button[name=quantity]").nth(1).click()  # +
            expect(drawer.locator("[aria-live=polite]").first).to_have_text("2")
            expect(page.locator("#cart-badge")).to_contain_text("2")
            drawer.locator("form[action*='/remove'] button").click()
            expect(drawer).to_contain_text("empty" if not prefix else "فارغة")
            page.locator("#cart-drawer button[data-hs-overlay]").first.click()
            expect(page.locator("#cart-drawer")).to_be_hidden()

        def header_opens_drawer() -> None:
            page.locator("[data-cart-trigger]").click()
            expect(page.locator("#cart-drawer")).to_be_visible()
            page.wait_for_timeout(400)
            page.keyboard.press("Escape")
            expect(page.locator("#cart-drawer")).to_be_hidden()

        def checkout_memory_and_fee() -> None:
            page.goto(B + prefix + "/p/leather-backpack")
            page.locator("[data-add-button]").click()
            expect(page.locator("#cart-drawer")).to_be_visible()
            page.goto(B + prefix + "/checkout")
            page.fill("#full_name", "Mona Ali")
            page.fill("#phone", "01001234567")
            page.select_option("#governorate", "alexandria")
            expect(page.locator("#checkout-totals")).to_contain_text("50")
            page.fill("#address", "5 Sea Road, Building 2")
            # Trigger the "remember" save without placing the order
            page.evaluate(
                "document.querySelector('[data-checkout-form]').dispatchEvent(new Event('submit'))"
            )
            page.goto(B + prefix + "/checkout")
            expect(page.locator("#full_name")).to_have_value("Mona Ali")
            expect(page.locator("#checkout-totals")).to_contain_text("50")

        def filters_htmx() -> None:
            page.goto(B + prefix + "/shop")
            before = page.locator("#results article").count()
            toggle = page.locator("#filters-toggle")
            if toggle.is_visible():  # mobile: filters live in a collapsed panel
                toggle.click()
                expect(page.locator("#filters-panel")).to_be_visible()
            page.locator("label:has(input[name=size][value='30'])").click()
            page.wait_for_url("**size=30**")
            after = page.locator("#results article").count()
            assert after < before and after >= 1, (before, after)

        for name, fn in [
            ("mobile menu", mobile_menu),
            ("variant picker", picker),
            ("add to bag + drawer + toast", add_and_drawer),
            ("drawer stepper + remove", stepper_and_remove),
            ("header bag opens drawer", header_opens_drawer),
            ("checkout memory + live fee", checkout_memory_and_fee),
            ("filters via htmx", filters_htmx),
        ]:
            check(f"{tag} {name}", fn)
        check(
            f"{tag} no JS errors",
            lambda: (_ for _ in ()).throw(AssertionError(errors)) if errors else None,
        )
        ctx.close()
    browser.close()

for name, ok, msg in results:
    print(("PASS " if ok else "FAIL ") + name + (f"  -> {msg}" if msg else ""))

"""Playwright, reduced motion (gondolas sway/animate; clicks aren't "stable" otherwise).
Covers: demo mode full play-through (no server calls), admin login+lookup+link-maker+cap box,
and a real player-mode play-through (uitest1) ending in the win popup with a live ladder amount.
Run BEFORE test_api.py — test_api.py spends juan123's/pedro's single daily spin and lowers the cap."""
import os
import re
import sys

from playwright.sync_api import sync_playwright

B = "http://127.0.0.1:8798"
OUT = os.path.dirname(__file__)
LADDER = ("₱17", "₱27", "₱37")
errs = []

with sync_playwright() as p:
    br = p.chromium.launch()
    ctx = br.new_context(viewport={"width": 460, "height": 900}, reduced_motion="reduce")

    # ---------- demo mode (no server calls) ----------
    d = ctx.new_page(); d.on("pageerror", lambda e: errs.append("demo: " + str(e)))
    d.goto(B + "/")
    d.wait_for_selector("#demoTag:not([hidden])")
    d.wait_for_selector(".gondola")
    assert d.locator(".gondola").count() == 8, d.locator(".gondola").count()
    d.locator(".gondola").nth(2).click()
    d.wait_for_selector("#startBtn:not([hidden])")
    d.click("#startBtn")
    d.wait_for_selector("#jp:not([hidden])", timeout=15000)
    amt = d.inner_text("#jpAmt")
    print("DEMO WIN:", amt)
    assert amt in LADDER, amt
    assert "DEMO" in d.inner_text("#jpSub"), d.inner_text("#jpSub")
    d.screenshot(path=os.path.join(OUT, "ui_demo.png"), full_page=True)
    d.click("#jpClose")
    d.wait_for_selector("#jp", state="hidden")

    # ---------- admin: wrong password, then real login, lookup, link maker, cap box ----------
    a = ctx.new_page(); a.on("pageerror", lambda e: errs.append("admin: " + str(e)))
    a.goto(B + "/#admin")
    a.wait_for_selector("#adminPass")
    a.fill("#adminPass", "wrong")
    a.click("#adminPassGo")
    a.wait_for_selector("#adminPassErr:has-text('Mali')")
    a.fill("#adminPass", "testpw")
    a.click("#adminPassGo")
    a.wait_for_selector("#adminBody:not([hidden])")
    a.wait_for_selector("#capText:has-text('₱10,000')")
    print("CAP:", a.inner_text("#capText"))

    a.fill("#acct", "uitest1")
    a.press("#acct", "Enter")
    a.wait_for_selector("#aTier:has-text('Wala pang napiling cabin')")
    a.click("#makeLink")
    a.wait_for_selector("#linkField:not([hidden])")
    link = a.inner_text("#plink")
    print("LINK:", link)
    assert re.search(r"^https?://[^/]+/#uitest1-[0-9a-f]{4}$", link), link
    a.screenshot(path=os.path.join(OUT, "ui_admin.png"), full_page=True)

    # ---------- real player: pick a cabin, goal already met (uitest1 is eligible), auto-spins ----------
    pl = ctx.new_page(); pl.on("pageerror", lambda e: errs.append("player: " + str(e)))
    pl.goto(link)
    pl.wait_for_selector("#who:has-text('UI Tester')")
    pl.wait_for_selector(".gondola")
    pl.check("#agree")
    pl.locator(".gondola").nth(4).click()
    pl.wait_for_selector("#jp:not([hidden])", timeout=20000)
    real_amt = pl.inner_text("#jpAmt")
    print("PLAYER WIN:", real_amt)
    assert real_amt in LADDER, real_amt
    assert "DEMO" not in pl.inner_text("#jpSub"), pl.inner_text("#jpSub")
    pl.screenshot(path=os.path.join(OUT, "ui_player.png"), full_page=True)
    pl.click("#jpClose")
    pl.wait_for_selector("#jp", state="hidden")
    pl.wait_for_selector("#hint:has-text('Nakuha mo')", timeout=10000)
    assert real_amt.replace("₱", "") in pl.inner_text("#hist"), pl.inner_text("#hist")

    # a second visit the same day shows the already-played state, no new spin offered
    pl.reload()
    pl.wait_for_selector("#hint:has-text('Nakuha mo')", timeout=10000)
    assert pl.is_hidden("#startBtn"), "no spin button once today's round is paid"

    # ---------- invalid/expired-looking code shows the invalid-link message ----------
    bad = ctx.new_page(); bad.on("pageerror", lambda e: errs.append("bad: " + str(e)))
    bad.goto(B + "/#ghost-abcd")
    bad.wait_for_selector("#hint:has-text('Hindi valid')", timeout=10000)

    br.close()

print("PAGE ERRORS:", errs or "none")
sys.exit(1 if errs else 0)

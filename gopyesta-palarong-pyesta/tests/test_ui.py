"""Playwright: admin lookup -> link -> Juan plays both entries; maria's page shows the locked state;
admin cap box renders. Run on a fresh seed, before test_api.py."""
import re, os, sys
from playwright.sync_api import sync_playwright
B = "http://127.0.0.1:8798"
OUT = os.path.dirname(__file__)
errs = []
with sync_playwright() as p:
    br = p.chromium.launch(); ctx = br.new_context(viewport={"width": 420, "height": 900}, reduced_motion="reduce")
    a = ctx.new_page(); a.on("pageerror", lambda e: errs.append("admin: " + str(e)))
    a.goto(B + "/#admin"); a.wait_for_selector("#adminPass")
    a.fill("#adminPass", "wrong"); a.click("#adminPassGo"); a.wait_for_selector("#adminPassErr:has-text('Mali')")
    a.fill("#adminPass", "testpw"); a.click("#adminPassGo"); a.wait_for_selector("#adminBody:not([hidden])")
    a.wait_for_selector("#capText:has-text('₱10,000')"); print("CAP:", a.inner_text("#capText"))
    a.fill("#acct", "juan123"); a.press("#acct", "Enter"); a.wait_for_selector("#aTier:has-text('Qualified')")
    tier = a.inner_text("#aTier"); print("ADMIN TIER:", tier.replace("\n", " | "))
    assert "2 entries" in tier and "2 pwede nang laruin" in tier, tier
    detail = a.inner_text("#offerBox"); print("ADMIN DETAIL:", detail.replace("\n", " | ")[:420])
    assert "₱450" in detail and "₱1,200" in detail and "pwede na" in detail and "₱80" in detail, detail
    a.click("#makeLink"); a.wait_for_selector("#linkField:not([hidden])")
    link = a.inner_text("#plink"); print("LINK:", link); assert re.search(r"#juan123-[0-9a-f]{4}$", link)
    # maria: locked entry visible in admin
    a.fill("#acct", "maria_x"); a.click("#lookupBtn"); a.wait_for_selector("#aTier:has-text('1 naka-lock')")
    assert "₱960" in a.inner_text("#offerBox"); a.click("#makeLink"); a.wait_for_selector("#linkField:not([hidden])"); mlink = a.inner_text("#plink")
    a.screenshot(path=os.path.join(OUT, "ui_admin.png"), full_page=True)

    pl = ctx.new_page(); pl.on("pageerror", lambda e: errs.append("player: " + str(e)))
    pl.goto(link); pl.wait_for_selector("#greeting:not([hidden])")
    assert "Para kay Juan Dela Cruz" in pl.inner_text("#greeting")
    pl.wait_for_selector("#entries:has-text('0/2')"); print("ENTRIES:", pl.inner_text("#entries"))
    assert pl.is_hidden("#resetBtn") and pl.is_hidden("#ladder") and pl.is_hidden("#mech")
    pl.click(".pot >> nth=0"); pl.wait_for_selector("#cheer:has-text('T&C')")
    pl.check("#agree")
    def play_once(page, n):
        page.click(".pot >> nth=1"); page.wait_for_selector("#goBtn:has-text('3 palo')")
        for _ in range(3): page.click("#goBtn")
        page.wait_for_selector("#jp:not([hidden])", timeout=8000); page.wait_for_timeout(1300); amt = page.inner_text("#jpAmt")
        print(f"PLAY {n} popup:", amt, "|", page.inner_text("#jpSub")); assert amt in ("₱17", "₱27", "₱37"), amt
        page.screenshot(path=os.path.join(OUT, f"ui_play{n}.png"))
        page.click("#jpClose"); page.wait_for_selector("#jp", state="hidden"); return amt
    a1 = play_once(pl, 1)
    pl.wait_for_selector("#entries:has-text('1/2')"); assert "1 pa" in pl.inner_text("#goBtn"), pl.inner_text("#goBtn")
    assert a1 in pl.inner_text("#results")
    pl.click("#goBtn"); pl.wait_for_selector("#goBtn:has-text('Pumili')")
    play_once(pl, 2)
    pl.wait_for_selector("#entries:has-text('2/2')"); assert "Ubos na" in pl.inner_text("#goBtn"); print("RESULTS:", pl.inner_text("#results"))
    pl.reload(); pl.wait_for_selector("#entries:has-text('2/2')"); assert "Ubos na" in pl.inner_text("#goBtn")
    pl.screenshot(path=os.path.join(OUT, "ui_player_after.png"), full_page=True)

    # maria: 1 playable + 1 locked -> after one play the page shows the locked state with a refresh button
    m = ctx.new_page(); m.on("pageerror", lambda e: errs.append("maria: " + str(e)))
    m.goto(mlink); m.wait_for_selector("#entries:has-text('naka-lock')"); print("MARIA:", m.inner_text("#entries"))
    m.check("#agree"); play_once(m, 3)
    m.wait_for_selector("#goBtn:has-text('naka-lock')"); print("MARIA NOTE:", m.inner_text("#note")[:160])
    assert "₱960" in m.inner_text("#note") and "₱400" in m.inner_text("#note")
    m.screenshot(path=os.path.join(OUT, "ui_locked.png"), full_page=True)

    bad = ctx.new_page(); bad.on("pageerror", lambda e: errs.append("bad: " + str(e)))
    bad.goto(B + "/#ghost-abcd"); bad.wait_for_selector("#entries:has-text('Hindi valid')"); assert bad.is_disabled("#goBtn")
    d = ctx.new_page(); d.on("pageerror", lambda e: errs.append("demo: " + str(e)))
    d.goto(B + "/"); d.wait_for_selector("#demoTag:not([hidden])"); d.check("#agree"); d.click(".pot >> nth=2")
    for _ in range(3): d.click("#goBtn")
    d.wait_for_selector("#jp:not([hidden])"); print("DEMO popup ok")
    br.close()
print("PAGE ERRORS:", errs or "none")
sys.exit(1 if errs else 0)

"""Playwright: admin lookup -> link -> player plays 2 entries. Leaves 2 entries for test_api.py."""
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
    a.fill("#acct", "juan123"); a.press("#acct", "Enter"); a.wait_for_selector("#aTier:has-text('Qualified')")
    tier = a.inner_text("#aTier"); print("ADMIN TIER:", tier.replace("\n", " | "))
    assert "4 entries" in tier and "₱400" in tier, tier
    detail = a.inner_text("#offerBox"); print("ADMIN DETAIL:", detail.replace("\n", " | ")[:300])
    assert "met" in detail and "13:30" in detail and "15:10" in detail, detail
    a.click("#makeLink"); a.wait_for_selector("#linkField:not([hidden])")
    link = a.inner_text("#plink"); print("LINK:", link); assert re.search(r"#juan123-[0-9a-f]{4}$", link)
    a.screenshot(path=os.path.join(OUT, "ui_admin.png"), full_page=True)

    pl = ctx.new_page(); pl.on("pageerror", lambda e: errs.append("player: " + str(e)))
    pl.goto(link); pl.wait_for_selector("#greeting:not([hidden])")
    assert "Para kay Juan Dela Cruz" in pl.inner_text("#greeting")
    pl.wait_for_selector("#entries:has-text('0/4')"); print("ENTRIES:", pl.inner_text("#entries"))
    assert pl.is_hidden("#resetBtn"), "reset must be hidden for players"
    assert pl.is_hidden("#ladder") and pl.is_hidden("#mech"), "odds must stay hidden pre-game"
    # T&C gate: tapping a pot without agreeing nudges
    pl.click(".pot >> nth=0"); pl.wait_for_selector("#cheer:has-text('T&C')")
    pl.check("#agree")
    def play_once(n):
        pl.click(".pot >> nth=1"); pl.wait_for_selector("#goBtn:has-text('3 palo')")
        for _ in range(3): pl.click("#goBtn")
        pl.wait_for_selector("#jp:not([hidden])", timeout=8000)
        amt = pl.inner_text("#jpAmt"); pl.wait_for_timeout(1300); amt = pl.inner_text("#jpAmt")
        print(f"PLAY {n} popup:", amt, "|", pl.inner_text("#jpSub"))
        assert amt in ("₱17", "₱27", "₱37"), amt
        pl.screenshot(path=os.path.join(OUT, f"ui_play{n}.png"))
        pl.click("#jpClose"); pl.wait_for_selector("#jp", state="hidden")
        return amt
    a1 = play_once(1)
    pl.wait_for_selector("#entries:has-text('1/4')"); assert "3 pa" in pl.inner_text("#goBtn"), pl.inner_text("#goBtn")
    assert a1 in pl.inner_text("#results")
    pl.click("#goBtn")  # Laro ulit
    pl.wait_for_selector("#goBtn:has-text('Pumili')")
    a2 = play_once(2)
    pl.wait_for_selector("#entries:has-text('2/4')"); print("RESULTS:", pl.inner_text("#results"))
    # reload: server state persists, fresh pots offered for the remaining entries
    pl.reload(); pl.wait_for_selector("#entries:has-text('2/4')"); assert pl.inner_text("#goBtn").startswith("Pumili")
    pl.screenshot(path=os.path.join(OUT, "ui_player_after.png"), full_page=True)
    # bogus link
    bad = ctx.new_page(); bad.on("pageerror", lambda e: errs.append("bad: " + str(e)))
    bad.goto(B + "/#ghost-abcd"); bad.wait_for_selector("#entries:has-text('Hindi valid')"); assert bad.is_disabled("#goBtn")
    # demo mode still works client-side
    d = ctx.new_page(); d.on("pageerror", lambda e: errs.append("demo: " + str(e)))
    d.goto(B + "/"); d.wait_for_selector("#demoTag:not([hidden])"); d.check("#agree"); d.click(".pot >> nth=2")
    for _ in range(3): d.click("#goBtn")
    d.wait_for_selector("#jp:not([hidden])"); print("DEMO popup ok")
    br.close()
print("PAGE ERRORS:", errs or "none")
sys.exit(1 if errs else 0)

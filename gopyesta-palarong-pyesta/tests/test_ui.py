"""Playwright: admin lookup -> link -> Juan spins both entries; maria's page shows the locked
state; admin cap box renders. Run on a fresh seed, before test_api.py.

NOTE (2026-10-09): the player half was rewritten for the Lucky Ferris Wheel, which replaced
Palosebo. The admin half is unchanged — the link maker kept its ids and its contract. This
file has NOT been executed against the new page: it needs Docker Postgres and Playwright,
neither of which was available where the rewrite was done. Treat a first run as unproven.

What changed on the player page:
  * one spin per entry, one click on #startBtn — no climber to pick, no 3 taps on #goBtn
  * a 3s countdown then a 5s wheel animation before the result, so waits are ~10s
  * the result is a #toast with .amt inside it, dismissed with #tOk (was #jp / #jpAmt / #jpClose)
  * entry counts live in #goalInfo and #liveTxt (was #entries), history in #hist (was #results)
  * opening the page with no link, or a bad one, shows the #gate overlay; there is no demo mode
"""
import re, os, sys
from playwright.sync_api import sync_playwright

B = "http://127.0.0.1:8798"
OUT = os.path.dirname(__file__)
PRIZES = ("₱10", "₱27", "₱57")
errs = []

with sync_playwright() as p:
    br = p.chromium.launch()
    ctx = br.new_context(viewport={"width": 420, "height": 900}, reduced_motion="reduce")

    # ---------- admin (unchanged) ----------
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
    link = a.inner_text("#plink"); print("LINK:", link)
    # the link maker and the game are two files now, so the link must point at / not /admin.html
    assert re.search(r"^https?://[^/]+/#juan123-[0-9a-f]{4}$", link), link
    a.fill("#acct", "maria_x"); a.click("#lookupBtn"); a.wait_for_selector("#aTier:has-text('1 naka-lock')")
    assert "₱960" in a.inner_text("#offerBox")
    a.click("#makeLink"); a.wait_for_selector("#linkField:not([hidden])"); mlink = a.inner_text("#plink")
    a.screenshot(path=os.path.join(OUT, "ui_admin.png"), full_page=True)

    # ---------- player ----------
    def spin_once(page, n):
        """One click, countdown, wheel, result toast. Returns the peso string."""
        page.click("#startBtn")
        page.wait_for_selector("#toast.on", timeout=20000)
        amt = page.inner_text("#toast .amt")
        print(f"SPIN {n}:", amt)
        assert amt in PRIZES, amt
        page.screenshot(path=os.path.join(OUT, f"ui_play{n}.png"))
        page.click("#tOk"); page.wait_for_selector("#toast.on", state="detached", timeout=10000)
        return amt

    pl = ctx.new_page(); pl.on("pageerror", lambda e: errs.append("player: " + str(e)))
    pl.goto(link)
    pl.wait_for_selector("#who:has-text('Juan Dela Cruz')")
    pl.wait_for_selector("#liveTxt:has-text('2 IKOT NA PWEDE')")
    print("ENTRIES:", pl.inner_text("#goalInfo").replace("\n", " | "))

    # the T&C gate: the button does nothing until the box is ticked, and no entry is spent
    pl.click("#startBtn")
    pl.wait_for_selector("#count:has-text('T&C')")
    assert pl.inner_text("#liveTxt") == "2 IKOT NA PWEDE", "a refused spin must not consume an entry"
    pl.check("#agree")

    a1 = spin_once(pl, 1)
    pl.wait_for_selector("#liveTxt:has-text('1 IKOT NA PWEDE')")
    assert a1 in pl.inner_text("#hist"), pl.inner_text("#hist")
    spin_once(pl, 2)
    pl.wait_for_selector("#hint:has-text('Ubos na')", timeout=15000)
    print("HISTORY:", pl.inner_text("#hist").replace("\n", " | "))
    pl.reload(); pl.wait_for_selector("#hint:has-text('Ubos na')", timeout=15000)
    assert pl.is_hidden("#startBtn"), "no spin button once the entries are used up"
    pl.screenshot(path=os.path.join(OUT, "ui_player_after.png"), full_page=True)

    # maria: 1 playable + 1 locked -> after one spin the page shows what turnover is still needed
    m = ctx.new_page(); m.on("pageerror", lambda e: errs.append("maria: " + str(e)))
    m.goto(mlink); m.wait_for_selector("#liveTxt:has-text('1 IKOT NA PWEDE')")
    m.check("#agree"); spin_once(m, 3)
    m.wait_for_selector("#liveTxt:has-text('NAKA-LOCK')", timeout=15000)
    note = m.inner_text("#hint"); print("MARIA NOTE:", note[:160])
    assert "₱960" in note and "turnover" in note.lower(), note
    m.screenshot(path=os.path.join(OUT, "ui_locked.png"), full_page=True)

    # a bad code and a bare URL both land on the gate; there is no demo mode any more
    bad = ctx.new_page(); bad.on("pageerror", lambda e: errs.append("bad: " + str(e)))
    bad.goto(B + "/#ghost-abcd")
    bad.wait_for_selector("#gate:not([hidden])")
    assert "valid" in bad.inner_text("#gateTitle").lower(), bad.inner_text("#gateTitle")
    d = ctx.new_page(); d.on("pageerror", lambda e: errs.append("nolink: " + str(e)))
    d.goto(B + "/"); d.wait_for_selector("#gate:not([hidden])")
    assert d.is_hidden("#startBtn")
    print("GATE ok for both a bad code and no code")
    br.close()

print("PAGE ERRORS:", errs or "none")
sys.exit(1 if errs else 0)

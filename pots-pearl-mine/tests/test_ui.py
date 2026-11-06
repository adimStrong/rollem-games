"""Playwright UI test for the server-driven Pearl Mine (run against a local app + fixture_pots.py; see README.md).
Usage: PYTHONIOENCODING=utf-8 python tests/test_ui.py [base_url]   (default http://127.0.0.1:8841)
Uses its OWN headless Chromium (never the shared browser). reduced_motion=reduce so every animation collapses."""
import json
import os
import sys
import urllib.request

from playwright.sync_api import expect, sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8841"
PW = os.environ.get("ADMIN_PASSWORD", "testpw")
LEDGER = os.path.join(os.path.dirname(__file__), "ledger_posts.jsonl")
errors = []
checks = 0


def ok(cond, label):
    global checks
    checks += 1
    if not cond:
        errors.append(label)
        print("  FAIL", label)
    else:
        print("  ok  ", label)


def api(path, method="GET", body=None, token=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **({"X-Admin-Token": token} if token else {})}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def admin_token():
    st, j = api("/api/admin-login", "POST", {"password": PW})
    assert st == 200, j
    return j["token"]


def make_link(token, account, fresh=False):
    st, j = api("/api/link", "POST", {"account": account, "fresh": fresh}, token)
    assert st == 200, (account, j)
    return j["code"]


def play_one(page, label):
    """START -> tap one clam -> COLLECT -> win card open. Returns amount text."""
    page.click("#goBtn")
    expect(page.locator(".pstage.live")).to_be_visible(timeout=15000)
    tile = page.locator(".bed .tile:not(.open)").first
    i = tile.get_attribute("data-i")
    tile.click(force=True)
    expect(page.locator(".bed .tile[data-i='%s'].open" % i)).to_be_visible(timeout=10000)
    expect(page.locator("#collectBtn")).to_be_visible(timeout=10000)
    page.click("#collectBtn")
    expect(page.locator("#jp")).to_be_visible(timeout=20000)
    amt = page.locator("#jpAmt").inner_text().strip()
    print("   ", label, "->", amt, "| sub:", page.locator("#jpSub").inner_text())
    return amt, i


def main():
    console = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(reduced_motion="reduce", viewport={"width": 420, "height": 900},
                                  permissions=["clipboard-read", "clipboard-write"])
        page = ctx.new_page()
        page.on("console", lambda m: console.append((m.type, m.text)) if m.type == "error" else None)
        page.on("pageerror", lambda e: (console.append(("pageerror", str(e))), print("   PAGEERROR @", page.url, "|", str(e), "|", (getattr(e, "stack", "") or "").replace("\n", " ")[:600])))

        # ---- demo ----
        print("[demo]")
        page.goto(BASE + "/")
        expect(page.locator("#demoTag")).to_be_visible()
        page.check("#agree")
        expect(page.locator("#goBtn")).to_have_text("START")
        amt, _ = play_one(page, "demo play 1")
        ok(amt in ("₱7", "₱17"), "demo amount drawn locally is 7 or 17: " + amt)
        ok("DEMO" in page.locator("#jpSub").inner_text(), "demo card tagged DEMO")
        page.click("#jpClose")
        expect(page.locator("#count")).to_have_text("Play 2 of 2")
        ok(True, "demo advances to play 2 of 2")

        # ---- admin ----
        print("[admin]")
        page.goto(BASE + "/#admin")
        page.reload()
        expect(page.locator("#admin")).to_be_visible()
        page.fill("#adminPass", "wrong")
        page.click("#adminPassGo")
        expect(page.locator("#adminPassErr")).to_have_text("Wrong password.")
        ok(True, "wrong password refused")
        page.fill("#adminPass", PW)
        page.click("#adminPassGo")
        expect(page.locator("#adminBody")).to_be_visible()
        expect(page.locator("#capText")).to_contain_text("₱10,000")
        ok("live" in page.locator("#stopText").inner_text(), "stop box shows live")
        page.fill("#acct", "uitest1")
        page.click("#lookupBtn")
        expect(page.locator("#aTier")).to_contain_text("3 plays", timeout=10000)
        ok("UI Tester" in page.locator("#aTier").inner_text(), "lookup shows real name")
        ok("₱450" in page.locator("#aTier").inner_text(), "lookup shows deposit ₱450")
        page.click("#makeLink")
        expect(page.locator("#plink")).to_contain_text("#uitest1-", timeout=10000)
        link = page.locator("#plink").inner_text().strip()
        ok(link.startswith(BASE + "/#uitest1-"), "player link built: " + link)
        page.click("#copyMsg")
        clip = page.evaluate("navigator.clipboard.readText()")
        ok("#uitest1-" in clip and "PEARL MINE" in clip and "₱150" in clip, "copy message + link contains announcement and link")
        expect(page.locator("#linksTodayList")).to_contain_text("uitest1", timeout=10000)
        ok(True, "links-today table lists uitest1")
        # not found
        page.fill("#acct", "ghost_zz")
        page.click("#lookupBtn")
        expect(page.locator("#aTier")).to_contain_text("Not found", timeout=10000)
        ok(True, "unknown account -> Not found")

        # ---- player: uitest1 plays 3 of 3 ----
        print("[player uitest1]")
        page.goto(link)
        page.reload()
        expect(page.locator("#who")).to_contain_text("UI Tester", timeout=10000)
        expect(page.locator("#count")).to_have_text("Play 1 of 3")
        page.check("#agree") if not page.is_checked("#agree") else None
        amounts = []
        for n in range(1, 4):
            amt, _ = play_one(page, "uitest1 play %d" % n)
            amounts.append(amt)
            ok("uitest1" in page.locator("#jpTicket").inner_text(), "card ticket names the player")
            page.click("#jpClose")
            if n < 3:
                expect(page.locator("#count")).to_have_text("Play %d of 3" % (n + 1), timeout=15000)
            else:
                expect(page.locator("#summary")).to_be_visible(timeout=15000)
        ok(all(a in ("₱7", "₱17") for a in amounts), "all 3 amounts in {7,17}: %s" % amounts)
        ok(page.locator("#sumList li").count() == 3, "summary lists 3 plays")
        ok("Deposit again" in page.locator("#note").inner_text(), "summary note explains the next play needs a new deposit")
        # START again must be gone
        ok(page.locator("#goBtn").is_hidden(), "no START after all plays used")
        tok = admin_token()
        st, j = api("/api/lookup?account=uitest1", token=tok)
        ok(j["playsUsed"] == 3 and all(pl["seen"] == 1 for pl in j["plays"]), "server: 3 plays, all seen")
        ok(all(pl["plan"] and pl["plan"]["end"] == "collect" for pl in j["plays"]), "server stored a finished plan for each play")

        # ---- maria_x: turnover-locked ----
        print("[player maria_x]")
        page.goto(BASE + "/#" + make_link(tok, "maria_x"))
        page.reload()
        expect(page.locator("#count")).to_have_text("Play 1 of 1", timeout=10000)
        expect(page.locator("#goBtn")).to_be_disabled()
        note = page.locator("#note").inner_text()
        ok("mag-slots pa ng ₱50" in note and "₱150" in note, "locked note shows turnover shortfall: " + note)
        st, j = api("/api/play/" + make_link(tok, "maria_x"), "POST")
        ok(st == 409 and j.get("error") == "locked", "POST /api/play refused while locked (%s %s)" % (st, j.get("error")))

        # ---- nodep ----
        print("[player nodep]")
        page.goto(BASE + "/#" + make_link(tok, "nodep"))
        page.reload()
        expect(page.locator("#range")).to_have_text("Waiting for a qualifying deposit.", timeout=10000)
        ok(page.locator("#goBtn").is_hidden(), "nodep: no START")

        # ---- juan123: resume mid-round after reload, unseen play after reload ----
        print("[player juan123 resume]")
        code = make_link(tok, "juan123")
        page.goto(BASE + "/#" + code)
        page.reload()
        expect(page.locator("#count")).to_have_text("Play 1 of 2", timeout=10000)
        page.click("#goBtn")
        expect(page.locator(".pstage.live")).to_be_visible(timeout=15000)
        tile = page.locator(".bed .tile:not(.open)").first
        i = tile.get_attribute("data-i")
        tile.click(force=True)
        expect(page.locator(".bed .tile[data-i='%s'].open" % i)).to_be_visible(timeout=10000)
        page.wait_for_timeout(800)  # let the plan POST land
        st, j = api("/api/session/" + code)
        plan = j["plays"][-1]["plan"]
        ok(plan and plan["taps"] == [int(i)] and plan["end"] is None, "server plan has the one tap and no end: %s" % (plan and plan["taps"]))
        vals_before = plan["vals"]
        page.reload()
        expect(page.locator(".pstage.live")).to_be_visible(timeout=15000)
        ok(page.locator(".bed .tile[data-i='%s'].open" % i).count() == 1, "after reload the same clam is open")
        ok(page.locator(".hfn").inner_text().strip() == "1", "after reload HUD shows 1 pearl found")
        page.click("#collectBtn")
        expect(page.locator("#jp")).to_be_visible(timeout=20000)
        st, j = api("/api/session/" + code)
        ok(j["plays"][-1]["plan"]["vals"] == vals_before and j["plays"][-1]["plan"]["end"] == "collect", "same pearls after resume, plan ended by collect")
        # reload with the card still open (unseen) -> result shown again, no re-roll
        amt1 = page.locator("#jpAmt").inner_text().strip()
        page.reload()
        expect(page.locator("#win")).to_be_visible(timeout=15000)
        ok(page.locator("#amt").inner_text().strip() == amt1, "unseen play shows the same amount after reload")
        expect(page.locator("#goBtn")).to_have_text("Next play")
        page.click("#showCard")
        expect(page.locator("#jp")).to_be_visible()
        page.click("#jpClose")
        expect(page.locator("#count")).to_have_text("Play 2 of 2", timeout=15000)
        ok(True, "claiming the unseen play advances to play 2 of 2")

        # ---- ledger ----
        rows = [json.loads(l) for l in open(LEDGER, encoding="utf-8")] if os.path.exists(LEDGER) else []
        ui = [r for r in rows if r.get("name") == "uitest1"]
        ok(len(ui) == 3 and all(r["amount"] in (7, 17) and r["brand"] == "pots" and r["game"] == "Pearl Mine" for r in ui),
           "ledger got 3 uitest1 rows (7/17, brand pots): %s" % [r["amount"] for r in ui])
        ok(not any(r.get("name") == "demo" for r in rows), "demo never posted to the ledger")

        bad = [c for c in console if not any(s in c[1] for s in ("net::ERR", "Failed to load resource", "WebGL", "THREE", "favicon"))]
        ok(not bad, "no console/page errors: %s" % bad[:5])
        browser.close()
    print("\n%d checks, %d failed" % (checks, len(errors)))
    for e in errors:
        print(" -", e)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()

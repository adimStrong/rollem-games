"""Playwright UI test for the server-driven Swerte Lights (run against a local app + fixture_tms.py; see README.md).
Usage: PYTHONIOENCODING=utf-8 python tests/test_ui.py [base_url]   (default http://127.0.0.1:8842)
Uses its OWN headless Chromium (never the shared browser). reduced_motion=reduce so the light run collapses.
A play here is START -> the lights run -> the win card opens (no taps); the plan is {cell, tier} or the wild layout."""
import json
import os
import re
import sys
import urllib.request

from playwright.sync_api import expect, sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8842"
PW = os.environ.get("ADMIN_PASSWORD", "testpw")
LEDGER = os.path.join(os.path.dirname(__file__), "ledger_posts.jsonl")
AMOUNTS = ("₱8.20", "₱16.50")
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


def count_text(page):
    return re.sub(r"\s+", " ", page.locator("#count").inner_text()).strip().lower()


def play_one(page, label):
    """START -> lights run -> win card open. Returns the amount on the card."""
    page.click("#goBtn")
    expect(page.locator("#jp")).to_be_visible(timeout=25000)
    amt = page.locator("#jpAmt").inner_text().strip()
    print("   ", label, "->", amt, "| sub:", page.locator("#jpSub").inner_text())
    return amt


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
        amt = play_one(page, "demo play 1")
        ok(amt in AMOUNTS, "demo amount drawn locally is 8.20 or 16.50: " + amt)
        ok("DEMO" in page.locator("#jpSub").inner_text(), "demo card tagged DEMO")
        page.click("#jpClose")
        page.wait_for_timeout(400)
        ok(count_text(page) == "play 2 of 2", "demo advances to play 2 of 2: " + count_text(page))

        # ---- admin ----
        print("[admin]")
        page.goto(BASE + "/#admin")
        page.reload()
        expect(page.locator("#admin")).to_be_visible()
        ok(page.locator("#goBtn").is_visible() and page.locator("#demoTag").is_visible(), "admin page shows the demo board preview")
        page.fill("#adminPass", "wrong")
        page.click("#adminPassGo")
        expect(page.locator("#adminPassErr")).to_have_text("Wrong password.")
        ok(True, "wrong password refused")
        page.fill("#adminPass", PW)
        page.click("#adminPassGo")
        expect(page.locator("#adminBody")).to_be_visible()
        expect(page.locator("#capText")).to_contain_text("₱15,000")
        ok("live" in page.locator("#stopText").inner_text(), "stop box shows live")
        page.fill("#acct", "uitest1")
        page.click("#lookupBtn")
        expect(page.locator("#aTier")).to_contain_text("3 plays", timeout=10000)
        tier = page.locator("#aTier").inner_text()
        ok("UI Tester" in tier, "lookup shows real name")
        ok("₱600" in tier, "lookup shows deposit ₱600")
        ok("all games" in tier.lower() and "slot" not in tier.lower(), "lookup says turnover counts all games: " + tier.replace("\n", " | ")[:200])
        page.click("#makeLink")
        expect(page.locator("#plink")).to_contain_text("#uitest1-", timeout=10000)
        link = page.locator("#plink").inner_text().strip()
        ok(link.startswith(BASE + "/#uitest1-"), "player link built: " + link)
        page.click("#copyMsg")
        clip = page.evaluate("navigator.clipboard.readText()")
        ok("#uitest1-" in clip and "SWERTE LIGHTS" in clip and "₱200" in clip, "copy message + link contains announcement and link")
        expect(page.locator("#linksTodayList")).to_contain_text("uitest1", timeout=10000)
        ok(True, "links-today table lists uitest1")
        page.fill("#acct", "ghost_zz")
        page.click("#lookupBtn")
        expect(page.locator("#aTier")).to_contain_text("Not found", timeout=10000)
        ok(True, "unknown account -> Not found")

        # ---- player: uitest1 plays 3 of 3 ----
        print("[player uitest1]")
        page.goto(link)
        page.reload()
        expect(page.locator("#who")).to_contain_text("UI Tester", timeout=10000)
        page.wait_for_timeout(300)
        ok(count_text(page) == "play 1 of 3", "uitest1 starts at play 1 of 3: " + count_text(page))
        page.check("#agree") if not page.is_checked("#agree") else None
        amounts = []
        for n in range(1, 4):
            amt = play_one(page, "uitest1 play %d" % n)
            amounts.append(amt)
            ok("uitest1" in page.locator("#jpTicket").inner_text(), "card ticket names the player")
            page.click("#jpClose")
            if n < 3:
                page.wait_for_timeout(1200)
                ok(count_text(page) == "play %d of 3" % (n + 1), "advances to play %d of 3: %s" % (n + 1, count_text(page)))
            else:
                expect(page.locator("#summary")).to_be_visible(timeout=15000)
        ok(all(a in AMOUNTS for a in amounts), "all 3 amounts in {8.20,16.50}: %s" % amounts)
        ok(page.locator("#sumList li").count() == 3, "summary lists 3 plays")
        ok("Deposit again" in page.locator("#note").inner_text(), "summary note explains the next play needs a new deposit")
        ok(page.locator("#goBtn").is_hidden(), "no START after all plays used")
        tok = admin_token()
        st, j = api("/api/lookup?account=uitest1", token=tok)
        ok(j["playsUsed"] == 3 and all(pl["seen"] == 1 for pl in j["plays"]), "server: 3 plays, all seen")
        ok(all(pl["plan"] and pl["plan"].get("done") for pl in j["plays"]), "server stored a finished plan for each play: %s" % [pl["plan"] for pl in j["plays"]])
        ok(all(("₱%.2f" % pl["amount"]) == a for pl, a in zip(j["plays"], amounts)), "card amounts == server amounts")

        # ---- maria_x: turnover-locked ----
        print("[player maria_x]")
        page.goto(BASE + "/#" + make_link(tok, "maria_x"))
        page.reload()
        page.wait_for_timeout(800)
        ok(count_text(page) == "play 1 of 1", "maria_x play 1 of 1: " + count_text(page))
        expect(page.locator("#goBtn")).to_be_disabled()
        note = page.locator("#note").inner_text()
        ok("₱100" in note and "₱200" in note and "turnover" in note, "locked note shows turnover shortfall: " + note)
        st, j = api("/api/play/" + make_link(tok, "maria_x"), "POST")
        ok(st == 409 and j.get("error") == "locked", "POST /api/play refused while locked (%s %s)" % (st, j.get("error")))

        # ---- nodep ----
        print("[player nodep]")
        page.goto(BASE + "/#" + make_link(tok, "nodep"))
        page.reload()
        expect(page.locator("#range")).to_have_text("Waiting for a qualifying deposit.", timeout=10000)
        ok(page.locator("#goBtn").is_hidden(), "nodep: no START")

        # ---- juan123: unseen play survives a reload (same amount, same stop cell) ----
        print("[player juan123 resume]")
        code = make_link(tok, "juan123")
        page.goto(BASE + "/#" + code)
        page.reload()
        page.wait_for_timeout(800)
        ok(count_text(page) == "play 1 of 2", "juan123 play 1 of 2: " + count_text(page))
        amt1 = play_one(page, "juan123 play 1")
        page.wait_for_timeout(800)  # let the plan POST land
        st, j = api("/api/session/" + code)
        plan = j["plays"][-1]["plan"]
        ok(plan and "cell" in plan and plan.get("done"), "server plan has a stop cell: %s" % plan)
        lit = page.evaluate("() => [...document.querySelectorAll('.cell')].findIndex(c => c.classList.contains('on') || c.classList.contains('hit') || c.classList.contains('win') || c.classList.contains('lit'))")
        page.reload()
        expect(page.locator("#win")).to_be_visible(timeout=15000)
        ok(page.locator("#amt").inner_text().strip() == amt1, "unseen play shows the same amount after reload")
        expect(page.locator("#goBtn")).to_have_text("Next play")
        st, j2 = api("/api/session/" + code)
        ok(j2["plays"][-1]["plan"] == plan, "plan unchanged after reload (no re-roll)")
        page.click("#showCard")
        expect(page.locator("#jp")).to_be_visible()
        ok(page.locator("#jpAmt").inner_text().strip() == amt1, "card replays the same amount")
        page.click("#jpClose")
        page.wait_for_timeout(1200)
        ok(count_text(page) == "play 2 of 2", "claiming the unseen play advances to play 2 of 2: " + count_text(page))

        # ---- ledger ----
        rows = [json.loads(l) for l in open(LEDGER, encoding="utf-8")] if os.path.exists(LEDGER) else []
        ui = [r for r in rows if r.get("name") == "uitest1"]
        ok(len(ui) == 3 and all(r["amount"] in (8.2, 16.5) and r["brand"] == "tamasa" and r["game"] == "Swerte Lights" for r in ui),
           "ledger got 3 uitest1 rows (8.2/16.5, brand tamasa): %s" % [r["amount"] for r in ui])
        ok(not any(r.get("name") == "demo" for r in rows), "demo never posted to the ledger")

        bad = [c for c in console if not any(s in c[1] for s in ("net::ERR", "Failed to load resource", "favicon"))]
        ok(not bad, "no console/page errors: %s" % bad[:5])
        browser.close()
    print("\n%d checks, %d failed" % (checks, len(errors)))
    for e in errors:
        print(" -", e)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()

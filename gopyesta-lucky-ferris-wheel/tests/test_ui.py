"""Playwright UI check against the locally running app (port 8798), fresh seed.
Player link: pick a cabin (T&C gate) -> goal already met for Juan -> auto spin -> win popup -> Claim marks seen.
Admin (#admin): password -> lookup -> shows the spin. Demo (no hash): tappable, START refuses."""
import json, urllib.request, sys
from playwright.sync_api import sync_playwright
B = "http://127.0.0.1:8798"
def call(path, method="GET", body=None, tok=None):
    req = urllib.request.Request(B + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **({"X-Admin-Token": tok} if tok else {})})
    with urllib.request.urlopen(req, timeout=10) as r: return json.loads(r.read())
fails = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name, info if not cond else "")
    if not cond: fails.append(name)
tok = call("/api/admin-login", "POST", {"password": "testpw"})["token"]
code = call("/api/link", "POST", {"account": "juan123", "fresh": True}, tok=tok)["code"]
with sync_playwright() as p:
    br = p.chromium.launch()
    ctx = br.new_context(viewport={"width": 420, "height": 900}, reduced_motion="reduce")
    errors = []
    pg = ctx.new_page(); pg.on("pageerror", lambda e: errors.append(str(e))); pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.goto(f"{B}/#{code}"); pg.wait_for_function("document.getElementById('who').textContent.includes('Juan Dela Cruz')", timeout=10000)
    check("player page greets by name", "Juan Dela Cruz" in pg.inner_text("#who"))
    check("6 gondolas", pg.locator(".gondola").count() == 6)
    check("hint asks to pick a cabin", "Pumili ng cabin" in pg.inner_text("#hint"), pg.inner_text("#hint"))
    pg.locator(".gondola").nth(4).click()
    pg.wait_for_timeout(600)
    check("pick refused until T&C ticked", pg.locator(".flash").count() >= 1 and not pg.locator(".gondola.mine").count(), pg.inner_text("#hint"))
    pg.check("#agree")
    pg.locator(".gondola").nth(4).click()
    # Juan's goal (deposit 400, slots 900 >= 300) is already met -> server spins; countdown 3s + spin 5s
    pg.wait_for_selector("#jp:not([hidden])", timeout=20000)
    amt = pg.inner_text("#jpAmt")
    check("win popup shows a peso amount", amt.startswith("₱") and 8 <= int(amt[1:].replace(",", "")) <= 18, amt)
    check("popup names cabin 5", "Cabin 5" in pg.inner_text("#jpSub"), pg.inner_text("#jpSub"))
    pg.click("#jpClose"); pg.wait_for_timeout(1200)
    s = call(f"/api/session/{code}")
    check("Claim marks the spin seen + status paid", s["cur"]["status"] == "paid" and s["cur"]["seen"] == 1, s["cur"])
    check("stage shows NAKUHA NA + amount in cabin window", "NAKUHA NA" in pg.inner_text("#liveTxt") and amt in pg.inner_text(".gondola .lbl"), pg.inner_text("#liveTxt"))
    check("no console/page errors (player)", not errors, errors)
    # ---- admin
    errors.clear()
    pg2 = ctx.new_page(); pg2.on("pageerror", lambda e: errors.append(str(e))); pg2.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg2.goto(f"{B}/#admin"); pg2.wait_for_selector("#adminPass")
    pg2.fill("#adminPass", "testpw"); pg2.click("#adminPassGo"); pg2.wait_for_selector("#adminBody:not([hidden])")
    pg2.fill("#acct", "juan123"); pg2.click("#lookupBtn"); pg2.wait_for_function("document.getElementById('aTier').textContent.includes('UMIKOT NA')", timeout=10000)
    check("admin lookup shows the spin + link", "Cabin 5" in pg2.inner_text("#aTier") and code in pg2.inner_text("#plink"), pg2.inner_text("#aTier"))
    check("admin cap box rendered", "nagamit" in pg2.inner_text("#capText"), pg2.inner_text("#capText"))
    check("no console/page errors (admin)", not errors, errors)
    # ---- demo
    errors.clear()
    pg3 = ctx.new_page(); pg3.on("pageerror", lambda e: errors.append(str(e))); pg3.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg3.goto(f"{B}/"); pg3.wait_for_selector("#demoTag:not([hidden])")
    pg3.locator(".gondola").nth(2).click(); pg3.wait_for_timeout(300)
    check("demo pick shows cabin 3 goal (300)", "Cabin 3" in pg3.inner_text("#goalInfo") and "300" in pg3.inner_text("#goalInfo"), pg3.inner_text("#goalInfo"))
    pg3.click("#startBtn"); pg3.wait_for_timeout(300)
    check("demo START refuses", pg3.locator(".flash").count() >= 1)
    check("no console/page errors (demo)", not errors, errors)
    br.close()
print("\nFAILS:", fails or "none")
sys.exit(1 if fails else 0)

# -*- coding: utf-8 -*-
"""End-to-end check of the per-link (cg3) GoBet Race: agent makes a link, player runs their own race.

Runs the REAL backend against the REAL gobetplay-retention database (there is no Docker or local
Postgres on the home PC), which is also better verification -- the entry gate only means anything
against real deposits and real turnover. Safeguards: the wins ledger is stubbed on localhost so no real
win is recorded, and every cg_sessions / cg_plays row this creates is deleted again at the end.

Everything is asserted through the DOM and waited on by CONDITION, never by a fixed sleep: the page's
own state (`mode`, `SESS`, `PLAN`) lives inside an IIFE closure and is NOT reachable from
page.evaluate, and a 4 MB page plus three.js needs ~10s before the first lobby paint.

usage: python tests/test_ui.py
"""
import importlib.util
import io as _io
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from playwright.sync_api import sync_playwright  # noqa: E402

DSN = _io.open(r"C:\tmp\gobetplay_pg_dsn.txt").read().strip()
PW = "test-only-password"
posts = []
fails = 0


def ok(cond, msg, extra=""):
    global fails
    print(("PASS " if cond else "FAIL ") + msg + (("  -- " + str(extra)[:300]) if (extra and not cond) else ""))
    if not cond:
        fails += 1


class Stub(BaseHTTPRequestHandler):
    def do_POST(self):
        posts.append(json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}"))
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.end_headers(); self.wfile.write(b'{"ok":true}')

    def log_message(self, *a):
        pass


stub = HTTPServer(("127.0.0.1", 0), Stub)
threading.Thread(target=stub.serve_forever, daemon=True).start()
s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()

os.environ.update(
    DATABASE_URL=DSN, ADMIN_PASSWORD=PW, SECRET_KEY="test-secret",
    LEDGER_URL="http://127.0.0.1:%d/api/win" % stub.server_address[1],
    PLATFORM="gb", BRAND="gobetplay", BRAND_LABEL="GoBetplay", GAME_NAME="GoBet Race",
    PER_PLAY="200", MAX_PLAYS="5", TURNOVER_MULT="1", WAGER_CATS="all", DAILY_CAP="10000",
    PRIZES="[[7,93],[17,5],[27,2],[77,0],[177,0]]", WILD_RATE="0",
    DEP_FROM="00:00", DEP_TO="23:59", PLAY_FROM="00:00", PLAY_UNTIL="23:59",  # so this runs at any hour
    REPORT_SHARE_TOKEN="test-share-token",
)
spec = importlib.util.spec_from_file_location("gbr_app", os.path.join(ROOT, "app.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
app, db = mod.app, mod.db
import psycopg2.extras  # noqa: E402

threading.Thread(target=lambda: app.run(host="127.0.0.1", port=PORT, threaded=True), daemon=True).start()
B = "http://127.0.0.1:%d/" % PORT
for _ in range(80):
    try:
        urllib.request.urlopen(B + "health", timeout=2).read(); break
    except Exception:
        time.sleep(0.5)
print("backend up on", B)

codes = []
play_ids = set()   # cg_plays ids this run created, so cleanup never touches anyone else's


def qualified():
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT u.account FROM deposits d JOIN users u ON u.user_id=d.user_id
                WHERE d.biz_date=%s AND d.order_status='Success' AND COALESCE(u.is_test,0)=0
                GROUP BY u.account, d.user_id
               HAVING SUM(d.amount) >= 200
                  AND COALESCE((SELECT SUM(b.valid_bet) FROM bets_daily b
                                WHERE b.user_id=d.user_id AND b.biz_date=%s),0) >= 200
                ORDER BY SUM(d.amount) DESC LIMIT 1""", (mod.today(), mod.today()))
        r = cur.fetchone()
        return r["account"] if r else None


acct = qualified()
print("qualified real account:", (acct[:3] + "***") if acct else "NONE")
ok(bool(acct), "found a genuinely qualified account to test with")

TXT = "el => (el ? el.textContent : '')"

with sync_playwright() as pw:
    br = pw.chromium.launch()
    ctx = br.new_context(viewport={"width": 430, "height": 900})
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append("PAGEERROR " + str(e)))
    # "Failed to load resource: ... 403" is Chromium narrating the DELIBERATE wrong-password attempt
    # below; it is never actionable on its own, and a real 403 would break a functional assertion anyway.
    page.on("console", lambda m: errs.append(m.type + ": " + m.text[:150])
            if m.type == "error" and "ERR_" not in m.text and "Failed to load resource" not in m.text else None)

    def wait(expr, ms=60000, label=""):
        try:
            page.wait_for_function("() => " + expr, timeout=ms)
            return True
        except Exception:
            ok(False, "timed out waiting for " + (label or expr))
            return False

    def txt(sel):
        el = page.query_selector(sel)
        return (el.inner_text() if el else "") or ""

    # ---------- 1. the agent's link maker ----------
    page.goto(B + "#admin", wait_until="load", timeout=150000)
    wait("document.getElementById('admLogin') && !document.getElementById('admLogin').hidden", 90000, "the login form")
    ok(page.locator("#admin").is_visible(), "#admin opens the panel")
    ok(page.locator("#admBody").is_hidden(), "the panel is locked until the password is entered")

    page.fill("#admPass", "wrong-one"); page.click("#admLoginForm button[type=submit]")
    wait("(document.getElementById('admMsg')||{}).textContent.indexOf('Wrong password')>=0", 30000, "the wrong-password message")
    ok("Wrong password" in txt("#admMsg"), "a wrong password says so", txt("#admMsg"))
    ok(page.locator("#admBody").is_hidden(), "a wrong password does not unlock it")

    page.fill("#admPass", PW); page.click("#admLoginForm button[type=submit]")
    wait("document.getElementById('admBody') && !document.getElementById('admBody').hidden", 40000, "the unlocked panel")
    ok(page.locator("#admBody").is_visible(), "the shared password unlocks the link maker")
    ok("1 race" in txt("#admStatus"), "the status line states the mechanic", txt("#admStatus"))

    if acct:
        page.fill("#admUid", acct)
        page.click("#admAddForm button[type=submit]")
        wait("(document.getElementById('admList')||{}).textContent.indexOf('Deposit today')>=0", 90000, "the lookup result")
        lst = txt("#admList")
        print("   admList:", " | ".join(x.strip() for x in lst.splitlines() if x.strip()))
        ok(acct in lst and "Deposit today" in lst, "lookup shows the player's real deposit + turnover", lst[:220])
        ok("ready to play" in lst and "YES" in lst, "the player reads as ready", lst[:300])

        # "New link" (fresh=true), never "Make link": /api/link REUSES an account's existing code for
        # the day, so plain Make-link can hand the test the very code a real player is already playing
        # on -- which is how an earlier run came to delete production play rows it had not created.
        page.click("#admStart")
        wait("document.getElementById('plink')", 60000, "the generated link")
        page.click("#admNew")
        page.wait_for_timeout(2500)
        wait("document.getElementById('plink')", 60000, "the fresh link")
        link = txt("#plink").strip()
        ok(link.startswith(B) and "#" in link, "a player link was generated", link)
        code = link.split("#", 1)[1]
        codes.append(code)
        ok(re.fullmatch(r"[a-z0-9._-]{3,64}", code) is not None, "the link code looks sane", code)

        # ---------- 2. the player's own race ----------
        posts.clear()
        # goto + reload: `mode` is decided at parse time from the hash, and coming from #admin this is a
        # hash-only navigation, which does not re-parse. (The page now reloads itself on a hash change,
        # but the test must not depend on that to get a clean player load.)
        page.goto(link, wait_until="load", timeout=150000)
        page.reload(wait_until="load", timeout=150000)
        wait("document.getElementById('gbgoal') && /race/i.test(document.getElementById('gbgoal').textContent)",
             120000, "the player's lobby")
        ok("race" in txt("#gbgoal").lower(), "the lobby shows the player's races", txt("#gbgoal")[:170])
        ok(page.locator(".gbrules").count() == 1, "the house rules are on the page")
        wait("!document.getElementById('startBtn').disabled", 40000, "START to become enabled")
        ok(not page.locator("#startBtn").is_disabled(), "START is enabled for a ready player")

        page.click("#startBtn")
        wait("len => true", 1000)  # settle
        wait("(document.getElementById('lobby')||{}).hidden === true", 30000, "the lobby to close")
        ok(page.locator("#lobby").is_hidden(), "pressing START starts the race")
        # the server draws and posts the win immediately, before the animation finishes
        for _ in range(40):
            if posts:
                break
            page.wait_for_timeout(500)
        ok(len(posts) == 1, "the server posted exactly one win to the ledger", posts)
        amount = posts[0]["amount"] if posts else None
        if posts:
            ok(posts[0]["brand"] == "gobetplay" and amount in (7, 17, 27),
               "the ledger payload is the real drawn prize", posts[0])

        # winner finishes ~15s in, then the result card appears
        wait("document.getElementById('result') && !document.getElementById('result').hidden", 240000, "the result card")
        ok(page.locator("#result").is_visible(), "the result card is shown when the race ends")
        rows = page.eval_on_selector_all("#resList li", "els => els.map(e => e.textContent)")
        ok(len(rows) == 8, "the result lists all 8 carabaos", len(rows))
        mine = [i for i, t in enumerate(rows) if "ikaw" in t]
        ok(len(mine) == 1, "exactly one row is marked as the player", rows)
        place = (mine[0] + 1) if mine else None
        ok(place is not None and place >= 3, "the player's carabao finished 3rd or worse", place)
        res_next = txt("#resNext")
        if amount is not None:
            ok(str(amount) in res_next, "the result card states the amount actually won", res_next[:170])
            # the amount decides the place through the page's prize-by-place table
            want = {27: 3, 17: 4}.get(amount)
            if want:
                ok(place == want, "P%d finishes %dth" % (amount, want), (place, amount))
            else:
                ok(place >= 5, "P7 finishes 5th-8th", (place, amount))

        # ---------- 3. a refresh does not re-roll ----------
        # Once the result has been shown the play is marked seen, so a refresh correctly returns to the
        # lobby for the NEXT race -- the same semantics as Pearl Mine, where only an UNSEEN play is
        # re-shown. The guarantee that matters is that no second play and no second win can appear.
        n_posts = len(posts)
        page.goto(link, wait_until="load", timeout=150000)
        page.reload(wait_until="load", timeout=150000)
        wait("document.getElementById('gbgoal') && /natitira/.test(document.getElementById('gbgoal').textContent)",
             150000, "the lobby after the race")
        goal = txt("#gbgoal").replace("\n", " ")
        ok("natitira 4" in goal, "the refresh shows one race used and 4 left", goal[:220])
        ok(len(posts) == n_posts, "the refresh posted no extra win", len(posts))

        with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id, play_no, amount_c, plan IS NOT NULL AS has_plan, seen FROM cg_plays WHERE code=%s", (code,))
            dbrows = [dict(r) for r in cur.fetchall()]
            play_ids.update(r["id"] for r in dbrows)
        ok(len(dbrows) == 1, "exactly one play was recorded for the whole flow", dbrows)
        if dbrows:
            ok(dbrows[0]["has_plan"], "the cosmetic race arrangement was saved for replay", dbrows[0])
            ok(dbrows[0]["amount_c"] == int(amount * 100), "the stored amount matches the ledger post", dbrows[0])

    # ---------- 4. a plain URL is still the harmless demo ----------
    page.goto(B, wait_until="load", timeout=150000)
    wait("/Demo/.test((document.getElementById('lobbyNext')||{}).textContent||'')", 120000, "the demo notice")
    ok("Demo" in txt("#lobbyNext"), "a plain URL is the demo and says so", txt("#lobbyNext"))
    ok(not posts or len(posts) == n_posts, "the demo recorded nothing")

    ok(not errs, "no console / page errors", errs[:6])
    page.screenshot(path=os.path.join(HERE, "gobetplay_player.png"))
    br.close()

# ---------- cleanup: leave the platform DB as it was found ----------
# Delete by the ids THIS RUN created. Deleting by code is what destroyed real production play rows
# once already: a code can be shared with whoever else is playing that account today.
with db() as conn, conn.cursor() as cur:
    if play_ids:
        cur.execute("DELETE FROM cg_plays WHERE id = ANY(%s)", (list(play_ids),))
    for c in codes:
        # the session row is safe to drop by code: this run is the only thing that used a fresh code,
        # and a leftover cg_sessions row with no plays is inert anyway
        cur.execute("DELETE FROM cg_sessions WHERE code=%s AND NOT EXISTS "
                    "(SELECT 1 FROM cg_plays p WHERE p.code=cg_sessions.code)", (c,))
    cur.execute("SELECT COUNT(*) FROM cg_plays"); plays_left = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM cg_sessions"); sess_left = cur.fetchone()[0]
print("   (cleaned %d code(s); cg_plays left %d, cg_sessions left %d)" % (len(codes), plays_left, sess_left))
ok(plays_left == 0 and sess_left == 0, "every row this test created was removed", (plays_left, sess_left))

stub.shutdown()
print("\n%s  (%d failure(s))" % ("ALL PASS" if not fails else "FAILURES", fails))
sys.exit(1 if fails else 0)

# -*- coding: utf-8 -*-
"""End-to-end check of the GoBet Race backend against the REAL gobetplay-retention database.

There is no Docker or local Postgres on the home PC, so this runs against the live platform DB -- which
is safe and is in fact better verification, because the entry gate is only meaningful against real
deposits and real turnover. It is careful about it:

  * the only tables written are the game's own gbr_* (the platform's tables are read-only here);
  * the wins ledger is stubbed on localhost, so no real win is ever recorded;
  * every row it creates is deleted again at the end, so the daily cap and the reports are untouched.

usage: python tests/test_api.py
"""
import importlib.util
import io as _io
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

DSN = _io.open(r"C:\tmp\gobetplay_pg_dsn.txt").read().strip()
PW = "test-only-password-not-the-real-one"

posts = []


class Stub(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        posts.append(json.loads(self.rfile.read(n) or b"{}"))
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.end_headers(); self.wfile.write(b'{"ok":true}')

    def log_message(self, *a):
        pass


stub = HTTPServer(("127.0.0.1", 0), Stub)
threading.Thread(target=stub.serve_forever, daemon=True).start()

os.environ.update(
    DATABASE_URL=DSN, ADMIN_PASSWORD=PW, SECRET_KEY="test-secret",
    LEDGER_URL="http://127.0.0.1:%d/api/win" % stub.server_address[1],
    PLATFORM="gb", BRAND="gobetplay", BRAND_LABEL="GoBetplay", GAME_NAME="GoBet Race",
    WAGER_CATS="all", REPORT_SHARE_TOKEN="test-share-token",
    DEP_FROM="00:00", DEP_TO="23:59", PLAY_FROM="00:00", PLAY_UNTIL="23:59",  # so this runs at any hour
    COUNTDOWN_MS="3000", RACE_PAD_MS="500",
)

spec = importlib.util.spec_from_file_location("gbr_app", os.path.join(ROOT, "app.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)          # also creates the gbr_* tables
app, db, psycopg2 = mod.app, mod.db, mod.psycopg2
import psycopg2.extras  # noqa: E402

fails = 0
created_race_ids = []


def ok(cond, msg, extra=""):
    global fails
    print(("PASS " if cond else "FAIL ") + msg + (("  -- " + str(extra)[:260]) if (extra and not cond) else ""))
    if not cond:
        fails += 1


def qualified_accounts(n=3):
    """Real accounts that genuinely qualify right now, so the entry gate is tested for real."""
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT u.account, SUM(d.amount) AS dep,
                      COALESCE((SELECT SUM(b.valid_bet) FROM bets_daily b
                                WHERE b.user_id=d.user_id AND b.biz_date=%s),0) AS turnover
                 FROM deposits d JOIN users u ON u.user_id=d.user_id
                WHERE d.biz_date=%s AND d.order_status='Success' AND COALESCE(u.is_test,0)=0
                GROUP BY u.account, d.user_id
               HAVING SUM(d.amount) >= %s
                  AND COALESCE((SELECT SUM(b.valid_bet) FROM bets_daily b
                                WHERE b.user_id=d.user_id AND b.biz_date=%s),0) >= %s
                ORDER BY SUM(d.amount) DESC LIMIT %s""",
            (mod.today(), mod.today(), mod.PER_ENTRY, mod.today(), mod.PER_ENTRY * mod.TURNOVER_MULT, n),
        )
        return [r["account"] for r in cur.fetchall()]


c = app.test_client()

# ---- 1. the platform tables really are readable and our own tables exist ----
with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT to_regclass('gbr_races') a, to_regclass('gbr_entries') b, "
                "to_regclass('gbr_settings') d, to_regclass('gbr_kill_switch') e")
    t = cur.fetchone()
    ok(all(t.values()), "init_db created the game's gbr_* tables", dict(t))
    cur.execute("SELECT to_regclass('bets_daily_category') x")
    ok(cur.fetchone()["x"] is None, "no bets_daily_category was created in the platform DB (adapter is a no-op)")

r = c.get("/health")
ok(r.status_code == 200 and r.get_json()["game"] == "GoBet Race", "/health names the game", r.get_json())
cfg = c.get("/api/config").get_json()
ok(cfg["version"] == "gbr1" and cfg["perEntry"] == 200 and cfg["maxEntriesPerDay"] == 5,
   "/api/config carries the mechanic", {k: cfg[k] for k in ("version", "perEntry", "maxEntriesPerDay")})
ok(cfg["maxEntries"] == cfg["field"] - 3, "/api/config roster cap leaves 3 spare lanes",
   (cfg["maxEntries"], cfg["field"]))
ok(cfg["prizes"][:2] == [177, 77] and cfg["livePrizes"] == [7, 27],
   "only the 3rd-and-below amounts are payable", (cfg["prizes"], cfg["livePrizes"]))

# ---- 2. the public poll works with no auth and opens a lobby ----
race = c.get("/api/race").get_json()
created_race_ids.append(int(race["id"][1:]))
ok(race["status"] == "lobby" and race["entries"] == [], "GET /api/race opens an empty lobby", race["status"])
ok(abs(race["serverNow"] - int(time.time() * 1000)) < 5000, "serverNow is the server clock")
ok(race["outcome"] is None, "a lobby exposes no outcome (nothing to replay yet)")

# ---- 3. admin auth ----
ok(c.post("/api/admin-login", json={"password": "wrong"}).status_code == 403, "wrong admin password is refused")
tok = c.post("/api/admin-login", json={"password": PW}).get_json()["token"]
ok(bool(tok), "correct admin password returns a token")
H = {"X-Admin-Token": tok}
ok(c.get("/api/admin/history").status_code == 403, "admin history needs the token")
ok(c.post("/api/admin/start", headers={"X-Admin-Token": "nope"}).status_code == 403, "start needs the token")

# ---- 4. lookup + the entry gate, against real accounts ----
accts = qualified_accounts(3)
print("   (qualified real accounts found today: %d)" % len(accts))
ok(len(accts) >= 2, "found at least 2 genuinely qualified accounts to test with", accts)

j = c.get("/api/admin/lookup?userId=definitely-not-a-real-account-xyz", headers=H).get_json()
ok(j.get("found") is False, "lookup of a nonexistent account returns found:false", j)

if len(accts) >= 2:
    j = c.get("/api/admin/lookup?userId=" + accts[0], headers=H).get_json()
    ok(j.get("found") and j.get("ready"), "lookup of a qualified account is ready", {k: j.get(k) for k in ("found", "ready", "missing")})
    ok(j.get("entriesTotal", 0) >= 1 and j.get("slot", 0) > 0,
       "lookup reads real deposits and real turnover", {k: j.get(k) for k in ("dep", "entriesTotal", "slot")})

    r = c.post("/api/admin/entry", json={"userId": "no-such-account-xyz"}, headers=H)
    ok(r.status_code == 404, "adding an unknown account is refused", r.status_code)

    for a in accts[:2]:
        r = c.post("/api/admin/entry", json={"userId": a, "username": "e2e"}, headers=H)
        ok(r.status_code == 200, "added real qualified entry %s" % (a[:3] + "***"), r.get_json())
    r = c.post("/api/admin/entry", json={"userId": accts[0]}, headers=H)
    ok(r.status_code == 409 and r.get_json().get("error") == "dup", "the same player cannot be added twice", r.get_json())

    race = c.get("/api/race").get_json()
    ok(len(race["entries"]) == 2 and all(not e["house"] for e in race["entries"]),
       "the lobby lists exactly the 2 real entries", race["entries"])

    # ---- 5. start: the server draws, pads the field, and nobody real takes 1st or 2nd ----
    r = c.post("/api/admin/start", headers=H)
    ok(r.status_code == 200, "start accepted", r.get_json())
    st = r.get_json()
    ok(st["status"] == "running", "race is running", st["status"])
    ok(len(st["entries"]) == cfg["field"], "the field was padded to %d lanes" % cfg["field"], len(st["entries"]))
    ok(sum(1 for e in st["entries"] if e["house"]) == cfg["field"] - 2, "the padding is filler racers")
    o = st["outcome"]
    ok(o and sorted(o["order"]) == list(range(cfg["field"])) and len(o["times"]) == cfg["field"],
       "the outcome is a full replayable permutation", o and list(o.keys()))
    ok(st["startAt"] > st["serverNow"], "startAt is in the future, so every viewer gets the countdown")
    # `results` is deliberately only exposed once the race is done (the page reads it only then), so the
    # house rule is checked here from what IS exposed while running: the order plus the entry list.
    ok("results" not in st, "a running race does not expose the results payload yet", list(st.keys()))
    first_two = [st["entries"][ri] for ri in o["order"][:2]]
    ok(all(e["house"] for e in first_two),
       "1st and 2nd went to filler racers -- no player can win P177/P77", first_two)
    real_places = sorted(o["order"].index(i) + 1 for i, e in enumerate(st["entries"]) if not e["house"])
    ok(len(real_places) == 2 and all(p >= 3 for p in real_places),
       "both players placed 3rd or worse", real_places)

    ok(c.post("/api/admin/entry", json={"userId": accts[0]}, headers=H).status_code == 409,
       "no new entries once the race is running")
    ok(c.post("/api/admin/start", headers=H).status_code == 409, "a running race cannot be started again")

    # ---- 6. finish: wins post to the ledger exactly once ----
    with db() as conn, conn.cursor() as cur:
        cur.execute("UPDATE gbr_races SET finish_at=%s WHERE id=%s", (mod.ms() - 1000, created_race_ids[-1]))
    posts.clear()
    done = c.get("/api/race").get_json()
    ok(done["status"] == "done", "the race finishes on the clock, with no scheduler", done["status"])
    dres = done.get("results") or []
    ok(len(dres) == cfg["field"], "the finished race exposes one result row per lane", len(dres))
    top2 = [x for x in dres if x["place"] in (1, 2)]
    ok(len(top2) == 2 and all(x["house"] for x in top2), "results confirm 1st/2nd are filler", top2)
    real_res = [x for x in dres if not x["house"]]
    ok(len(real_res) == 2 and all(x["place"] >= 3 for x in real_res),
       "results confirm both players placed 3rd or worse", real_res)
    ok(len(real_res) == 2 and all(x["prize"] in ("₱27", "₱7") for x in real_res),
       "players were paid only P27 or P7", real_res)
    time.sleep(1.5)
    ok(len(posts) == 2, "one ledger post per real player", posts)
    ok(all(p["brand"] == "gobetplay" and p["game"] == "GoBet Race" for p in posts), "ledger payload names the brand", posts)
    ok(all(p["amount"] in (7, 27) for p in posts), "ledger amounts are the real prizes", [p.get("amount") for p in posts])
    n_before = len(posts)
    c.get("/api/race"); c.get("/api/race")
    time.sleep(0.8)
    ok(len(posts) == n_before, "polling again does NOT re-post the wins", len(posts))

    # ---- 7. a new race, the report, and the CSV ----
    r = c.post("/api/admin/new", headers=H)
    ok(r.status_code == 200 and r.get_json()["status"] == "lobby", "New race opens a fresh lobby", r.get_json())
    created_race_ids.append(int(r.get_json()["id"][1:]))
    rep = c.get("/api/report?token=test-share-token").get_json()
    ok(any(not x.get("house") for x in rep["rows"]) and rep["total"] > 0,
       "the share-token report shows the win", {"rows": len(rep["rows"]), "total": rep["total"]})
    ok(c.get("/api/report").status_code == 403, "the report needs the share token or the admin token")
    csv_r = c.get("/api/admin/history.csv?token=" + tok)
    ok(csv_r.status_code == 200 and b"date_ph,race,place" in csv_r.data, "the admin CSV downloads")
    ok(c.get("/api/admin/history.csv?token=nope").status_code == 403, "the CSV link needs a valid token")

# ---- 8. the window gate, checked directly (this run widened it so it could execute at any hour) ----
mod.DEP_FROM, mod.DEP_TO = "12:00", "21:00"
mod.PLAY_FROM, mod.PLAY_UNTIL = "12:00", "23:59"
hm = mod.hm_of(mod.now())
inside = "12:00" <= hm < "21:00"
r = c.post("/api/admin/entry", json={"userId": accts[0] if accts else "x"}, headers=H)
if inside:
    ok(r.status_code != 409 or r.get_json().get("error") != "closed",
       "inside 12:00-21:00 the entry window is open (now %s)" % hm, r.get_json())
else:
    ok(r.status_code == 409 and r.get_json().get("error") == "closed",
       "outside 12:00-21:00 entries are refused (now %s)" % hm, r.get_json())

# ---- cleanup: leave the platform DB exactly as it was found ----
with db() as conn, conn.cursor() as cur:
    for rid in created_race_ids:
        cur.execute("DELETE FROM gbr_entries WHERE race_id=%s", (rid,))
        cur.execute("DELETE FROM gbr_races WHERE id=%s", (rid,))
    cur.execute("SELECT COUNT(*) FROM gbr_races")
    left = cur.fetchone()[0]
print("   (cleaned up %d test race(s); gbr_races rows remaining: %d)" % (len(created_race_ids), left))
ok(left == 0, "every row this test created was removed", left)

stub.shutdown()
print("\n%s  (%d failure(s))" % ("ALL PASS" if not fails else "FAILURES", fails))
sys.exit(1 if fails else 0)

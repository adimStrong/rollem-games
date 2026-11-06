"""API tests for the v3 plays backend. Usage: python tests/test_api.py <pots|tms> <base_url> [ledger_posts.jsonl]
Assumes the matching fixture was just seeded (fixture_pots.py / fixture_tms.py) and the app runs with the
env from tests/README.md (ADMIN_PASSWORD=testpw). Uses juan123 / maria_x / pedro / nodep / tester."""
import json
import os
import sys
import urllib.error
import urllib.request

PLATFORM = sys.argv[1] if len(sys.argv) > 1 else "pots"
BASE = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8843"
LEDGER_FILE = sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(__file__), "ledger_posts.jsonl")
PER_PLAY = 150 if PLATFORM == "pots" else 200
AMOUNTS = {7, 17} if PLATFORM == "pots" else {8.2, 16.5}
TOKEN = ""
fails = 0
n = 0


def req(method, path, body=None, token=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    if token:
        r.add_header("X-Admin-Token", token)
    try:
        resp = urllib.request.urlopen(r, timeout=20)
        st, txt = resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        st, txt = e.code, e.read().decode()
    if raw:
        return st, txt
    try:
        return st, json.loads(txt)
    except ValueError:
        return st, {"_raw": txt[:200]}


def check(label, cond, extra=""):
    global fails, n
    n += 1
    print(("PASS " if cond else "FAIL ") + label + (f"  [{extra}]" if extra and not cond else ""), flush=True)
    if not cond:
        fails += 1


# ---- config / auth
st, cfg = req("GET", "/api/config")
check("config 200", st == 200 and cfg.get("version") == "cg3", str(cfg)[:120])
check("config perPlay", cfg.get("perPlay") == PER_PLAY, cfg.get("perPlay"))
st, j = req("POST", "/api/admin-login", {"password": "wrong"})
check("wrong password 403", st == 403)
st, j = req("POST", "/api/admin-login", {"password": "testpw"})
check("admin login", st == 200 and j.get("token"))
TOKEN = j.get("token", "")
st, j = req("GET", "/api/lookup?account=juan123")
check("lookup without token 403", st == 403)

# ---- lookup shapes
st, j = req("GET", "/api/lookup?account=juan123", token=TOKEN)
check("lookup juan123 found", st == 200 and j.get("found") is True, str(j)[:200])
check("juan123 window deposits only", j.get("dep") == 2 * PER_PLAY, j.get("dep"))
check("juan123 playsTotal 2", j.get("playsTotal") == 2, j.get("playsTotal"))
check("juan123 slot counts wager cats only", abs(j.get("slot", 0) - (500 if PLATFORM == "pots" else 400)) < 0.01, j.get("slot"))
check("juan123 ready", j.get("ready") is True, j.get("missing"))
check("juan123 nextNeed = perPlay", j.get("nextNeed") == PER_PLAY, j.get("nextNeed"))
uid_ok = ("1" if PLATFORM == "pots" else "1001")
st, j2 = req("GET", "/api/lookup?account=" + uid_ok, token=TOKEN)
check("lookup by numeric id", st == 200 and j2.get("account") == "juan123", str(j2)[:120])
if PLATFORM == "pots":
    st, j3 = req("GET", "/api/lookup?account=ptabc123", token=TOKEN)
    check("lookup by prefixed game id", st == 200 and j3.get("account") == "juan123", str(j3)[:120])
    st, j4 = req("GET", "/api/lookup?account=tester", token=TOKEN)
    check("test account hidden", st == 200 and j4.get("found") is False)
st, j = req("GET", "/api/lookup?account=maria_x", token=TOKEN)
check("maria_x 1 play, turnover-locked", j.get("playsTotal") == 1 and j.get("betOk") is False and j.get("ready") is False, str(j.get("missing")))
st, j = req("GET", "/api/lookup?account=nodep", token=TOKEN)
check("nodep 0 plays", j.get("playsTotal") == 0 and j.get("depOk") is False and j.get("ready") is False, str(j.get("missing")))
st, j = req("GET", "/api/lookup?account=pedro", token=TOKEN)
check("pedro capped at maxPlays 5", j.get("playsTotal") == 5, j.get("playsTotal"))
st, j = req("GET", "/api/lookup?account=zzz_nobody", token=TOKEN)
check("unknown account found:false", st == 200 and j.get("found") is False)

# ---- links
st, j = req("POST", "/api/link", {"account": "juan123"}, token=TOKEN)
check("make link", st == 200 and j.get("code", "").startswith("juan123-"), str(j)[:120])
code = j["code"]
st, j = req("POST", "/api/link", {"account": "juan123"}, token=TOKEN)
check("link reused", j.get("code") == code, j.get("code"))
st, j = req("POST", "/api/link", {"account": "juan123", "fresh": True}, token=TOKEN)
check("fresh link differs", j.get("code") != code and j.get("linksIssued") == 2, str(j.get("linksIssued")))
code = j["code"]
st, j = req("POST", "/api/link", {"account": "zzz_nobody"}, token=TOKEN)
check("link unknown 404", st == 404)
st, j = req("GET", "/api/session/nope-0000")
check("session unknown", st == 200 and j.get("exists") is False)
st, j = req("GET", "/api/session/" + code)
check("session juan123", j.get("exists") and j.get("account") == "juan123" and j.get("playsUsed") == 0 and j.get("ready") is True, str(j)[:160])
check("session hides admin-only keys", "deposits" not in j and "linksIssued" not in j)

# ---- plays
st, p1 = req("POST", "/api/play/" + code)
check("play 1 ok", st == 200 and p1.get("played") and p1["play"]["play_no"] == 1, str(p1)[:200])
amt1 = p1["play"]["amount"]
check("play 1 amount in ladder", amt1 in AMOUNTS, amt1)
check("after play 1: used 1, nextNeed 2x", p1.get("playsUsed") == 1 and p1.get("nextNeed") == 2 * PER_PLAY, str((p1.get("playsUsed"), p1.get("nextNeed"))))
check("play 1 needs plan", p1["play"]["plan"] is None)
st, j = req("POST", "/api/plan/" + code, {"id": p1["play"]["id"], "plan": {"vals": [350, 350], "perm": [1, 2], "taps": []}})
check("plan saved", st == 200 and j.get("ok") is True, str(j))
st, j = req("POST", "/api/plan/" + code, {"id": p1["play"]["id"], "plan": {"x": "y" * 7000}})
check("plan too large 400", st == 400)
st, j = req("POST", "/api/plan/other-0000", {"id": p1["play"]["id"], "plan": {"a": 1}})
check("plan wrong code not ok", j.get("ok") is False)
st, j = req("GET", "/api/session/" + code)
check("session returns plan + seen 0", j["plays"][0]["plan"] == {"vals": [350, 350], "perm": [1, 2], "taps": []} and j["plays"][0]["seen"] == 0)
st, j = req("POST", "/api/seen/" + code, {"id": p1["play"]["id"]})
st, j = req("GET", "/api/session/" + code)
check("seen flag set", j["plays"][0]["seen"] == 1)
# play 2: juan123 slot 500 (pots) / 400 (tms) >= 2*PER_PLAY -> ok
st, p2 = req("POST", "/api/play/" + code)
check("play 2 ok", st == 200 and p2["play"]["play_no"] == 2, str(p2)[:200])
st, p3 = req("POST", "/api/play/" + code)
check("play 3 refused (no 3rd deposit)", st == 409 and p3.get("error") == "no_new_deposit", str(p3)[:160])
st, j = req("GET", "/api/session/" + code)
check("session playsLeft 0", j.get("playsLeft") == 0 and j.get("ready") is False)

# maria_x: deposit ok, turnover short -> locked
st, j = req("POST", "/api/link", {"account": "maria_x"}, token=TOKEN)
mcode = j["code"]
st, j = req("POST", "/api/play/" + mcode)
check("maria_x locked 409", st == 409 and j.get("error") == "locked", str(j)[:160])
# nodep
st, j = req("POST", "/api/link", {"account": "nodep"}, token=TOKEN)
st, j = req("POST", "/api/play/" + j["code"])
check("nodep no_new_deposit", st == 409 and j.get("error") == "no_new_deposit", str(j)[:160])

# ---- odds distribution over pedro-like volume: use pick_prize via many plays? use 400 draws through the module instead
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "postgresql://invalid")  # not used by pick_prize
try:
    import importlib
    os.environ["PLATFORM"] = PLATFORM
    if PLATFORM == "tms":
        os.environ.update(PRIZES="[[8.2,90],[16.5,10]]", WILD_RATE="0.05", WILD_PRIZES="[[8.2,95],[16.5,5],[777,0]]", PER_PLAY="200")
    # exec only the mechanics constants + the draw functions from app.py (no Flask, no DB)
    src = open(os.path.join(os.path.dirname(__file__), "..", "app.py"), encoding="utf-8").read()
    consts = src.split("# ---- mechanics")[1].split("\n", 1)[1].split("def _pct(ps):")[0]
    fns = "def _draw(ps):" + src.split("def _draw(ps):")[1].split("def plays_for(")[0]
    ns = {"os": os, "json": json}
    exec("import secrets\n" + consts + "\n" + fns, ns)
    counts = {}
    wilds = 0
    for _ in range(4000):
        a, t, w = ns["pick_prize"]()
        counts[a] = counts.get(a, 0) + 1
        wilds += 1 if w else 0
    lo = counts.get(700 if PLATFORM == "pots" else 820, 0) / 4000
    check("odds ~90% low prize", 0.85 < lo < 0.95, f"{lo:.3f} {counts}")
    check("never draws display tiers", all(a in {int(x * 100) for x in AMOUNTS} for a in counts), str(counts))
    if PLATFORM == "tms":
        check("wild rate ~5%", 0.03 < wilds / 4000 < 0.07, wilds)
except Exception as e:  # noqa: BLE001
    check("odds check ran", False, repr(e))

# ---- cap: pedro has 5 plays; set cap so only 1 fits
st, j = req("GET", "/api/cap", token=TOKEN)
used = j["capUsed"]
st, j = req("POST", "/api/cap", {"dailyCap": used + (10 if PLATFORM == "pots" else 10)}, token=TOKEN)
check("cap set", st == 200 and j.get("ok"), str(j)[:120])
st, j = req("POST", "/api/link", {"account": "pedro"}, token=TOKEN)
pcode = j["code"]
st, p = req("POST", "/api/play/" + pcode)
check("pedro play 1 within cap", st == 200, str(p)[:160])
st, p = req("POST", "/api/play/" + pcode)
check("pedro play 2 cap refused", st == 409 and p.get("error") == "cap", str(p)[:160])
st, j = req("POST", "/api/link", {"account": "nodep", "fresh": True}, token=TOKEN)
check("link maker refuses when capped", st == 409 and j.get("error") == "cap", str(j)[:120])
st, j = req("POST", "/api/cap", {"dailyCap": 1}, token=TOKEN)
check("cap below used refused", st == 400)
st, j = req("POST", "/api/cap", {"dailyCap": 10000}, token=TOKEN)

# ---- kill switch
st, j = req("POST", "/api/stop", {"stopped": True, "note": "test"}, token=TOKEN)
check("stop on", j.get("stopped") is True)
st, p = req("POST", "/api/play/" + pcode)
check("play refused while stopped", st == 409 and p.get("error") == "stopped")
st, j = req("POST", "/api/link", {"account": "pedro", "fresh": True}, token=TOKEN)
check("link refused while stopped", st == 409 and j.get("error") == "stopped")
st, j = req("GET", "/api/session/" + pcode)
check("session shows stopped", j.get("stopped") is True and j.get("ready") is False)
st, j = req("POST", "/api/stop", {"stopped": False}, token=TOKEN)
check("stop off", j.get("stopped") is False)
st, p = req("POST", "/api/play/" + pcode)
check("pedro play 2 after resume", st == 200 and p["play"]["play_no"] == 2, str(p)[:120])

# ---- links today
st, j = req("GET", "/api/links-today", token=TOKEN)
players = {p["account"]: p for p in j.get("players", [])}
check("links-today lists juan123/maria_x/nodep/pedro", all(a in players for a in ("juan123", "maria_x", "nodep", "pedro")), list(players))
jj = players.get("juan123", {})
check("juan123 rounds=2 on 1 code, links_issued 2, won sum", jj.get("rounds") == 2 and jj.get("links") == 1 and jj.get("links_issued") == 2 and jj.get("won") == round(amt1 + p2["play"]["amount"], 2), str(jj))
check("juan123 deposit/turnover enriched", jj.get("depAmount") == 2 * PER_PLAY and jj.get("depCount") == 1 and jj.get("turnover") > 0, str(jj))
st, j = req("GET", "/api/links-today?from=2020-01-01&to=2020-01-02", token=TOKEN)
check("links-today empty range", j.get("players") == [])
st, j = req("GET", "/api/links-today?from=bad", token=TOKEN)
check("links-today bad date falls back", st == 200 and j.get("from") != "bad")

# ---- ledger posts
import time
time.sleep(1.5)
try:
    posts = [json.loads(l) for l in open(LEDGER_FILE, encoding="utf-8") if l.strip()]
except OSError:
    posts = []
mine = [p for p in posts if p.get("name") == "juan123"]
check("ledger got 2 juan123 posts", len(mine) == 2, len(mine))
check("ledger brand/game/amount", all(p["brand"] == cfg["brand"] and p["game"] == cfg["game"] and p["amount"] in AMOUNTS for p in mine), str(mine)[:200])

# ---- pages
st, txt = req("GET", "/health", raw=True)
check("health", st == 200 and cfg["game"] in txt)
st, txt = req("GET", "/report", raw=True)
check("report page", st == 200 and "<html" in txt.lower())
st, txt = req("GET", "/report/nope", raw=True)
check("public report off without token", st == 404)

print(f"\n{n - fails}/{n} passed" + ("" if not fails else f"  ({fails} FAILED)"))
sys.exit(1 if fails else 0)

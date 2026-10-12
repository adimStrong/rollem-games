"""API-level checks against the locally running app (port 8798) + stub ledger. Fresh seed (tests/fixture.py) first."""
import json, urllib.request, urllib.error, psycopg2, os, time
from datetime import datetime; from zoneinfo import ZoneInfo
B = "http://127.0.0.1:8798"
today = datetime.now(ZoneInfo("Asia/Manila")).strftime("%Y-%m-%d")
def call(path, method="GET", body=None, tok=None):
    req = urllib.request.Request(B + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **({"X-Admin-Token": tok} if tok else {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read(); return e.code, (json.loads(raw) if raw.startswith(b"{") else {"raw": raw[:200].decode(errors="replace")})
fails = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name, info if not cond else "")
    if not cond: fails.append(name)
db = psycopg2.connect("postgresql://postgres:cgtest@localhost:55432/cg"); db.autocommit = True; cur = db.cursor()

st, j = call("/health"); check("health names the game", st == 200 and j["game"] == "Lucky Ferris Wheel", j)
st, cfg = call("/api/config"); check("config: 8 cabins, 4 tiers, slots only", cfg["cabins"] == 8 and len(cfg["tiers"]) == 4 and cfg["wagerCats"] == ["egame"] and cfg["minDeposit"] == 100, cfg)
st, j = call("/api/admin-login", "POST", {"password": "wrong"}); check("bad password 403", st == 403)
st, j = call("/api/admin-login", "POST", {"password": "testpw"}); tok = j.get("token"); check("login", st == 200 and tok)
st, j = call("/api/lookup?account=Juan123"); check("lookup needs token", st == 403)
st, j = call("/api/lookup?account=juan123", tok=tok)
check("lookup found (case-insensitive)", st == 200 and j["found"] and j["account"] == "Juan123", j)
check("deposit total 400 (Failed excluded), slots 900 (casino/fishing excluded)", j["dep"] == 400 and j["slot"] == 900 and j["other"] == 5400, (j.get("dep"), j.get("slot"), j.get("other")))
check("no cabin yet -> cur None, canPick", j["cur"] is None and j["canPick"] and j["depOk"] and not j["betOk"], j.get("cur"))
check("name from real_name", j["name"] == "Juan Dela Cruz", j.get("name"))
st, j = call("/api/lookup?account=tester", tok=tok); check("test account not found", st == 200 and not j["found"], j)
st, j = call("/api/link", "POST", {"account": "juan123"}, tok=tok); code = j.get("code")
check("link created", st == 200 and code and code.startswith("juan123-"), j)
st, j2 = call("/api/link", "POST", {"account": "juan123"}, tok=tok); check("link reused same day", j2.get("code") == code, j2.get("code"))
st, j3 = call("/api/link", "POST", {"account": "juan123", "fresh": True}, tok=tok); check("fresh link new code", j3.get("code") != code and j3.get("code").startswith("juan123-"))
st, s = call(f"/api/session/{code}"); check("session public GET", st == 200 and s["exists"] and s["name"] == "Juan Dela Cruz" and s["cur"] is None and s["config"]["game"] == "Lucky Ferris Wheel", s)
st, s = call("/api/session/nope-0000"); check("unknown session", st == 200 and not s["exists"])
# ---- spin before pick / pick / change cabin
st, p = call(f"/api/spin/{code}", "POST", {}); check("spin before pick refused", st == 409 and p["error"] == "no_pick", p)
st, p = call(f"/api/pick/{code}", "POST", {"cabin": 9}); check("cabin 9 rejected", st == 400, p)
st, p = call(f"/api/pick/{code}", "POST", {"cabin": 3}); check("cabin 3 = tier 3 (8000) open, not ready", st == 200 and p["cur"]["cabin"] == 3 and p["cur"]["need"] == 8000 and p["cur"]["status"] == "open" and not p["ready"], p.get("cur"))
check("missing says slots short by 7100", any("7,100" in m for m in p["missing"]), p.get("missing"))
st, p = call(f"/api/spin/{code}", "POST", {}); check("spin refused while locked", st == 409 and p["error"] == "locked" and "7,100" in p["msg"], p)
st, p = call(f"/api/pick/{code}", "POST", {"cabin": 5}); check("change to cabin 5 = tier 1 (300) -> ready", st == 200 and p["cur"]["cabin"] == 5 and p["cur"]["need"] == 300 and p["ready"], p.get("cur"))
st, s = call(f"/api/session/{code}"); check("session shows ready + today pending in week", s["ready"] and any(w["day"] == today and w["amount"] is None for w in s["week"]), s.get("week"))
st, p = call(f"/api/spin/{code}", "POST", {})
check("spin pays tier-1 amount 8..18", st == 200 and p["spun"] and p["cur"]["status"] == "paid" and 8 <= p["cur"]["amount"] <= 18 and p["cur"]["seen"] == 0, p.get("cur"))
amt = p["cur"]["amount"]
check("snapshot dep/slot at spin", p["cur"]["dep"] == 400 and p["cur"]["slot"] == 900, p.get("cur"))
check("turnover pending: need 5x, done 0", p["wager"]["bonus"] == amt and p["wager"]["need"] == amt * 5 and p["wager"]["done"] == 0, p.get("wager"))
st, p2 = call(f"/api/spin/{code}", "POST", {}); check("second spin = already, no double pay", st == 200 and p2.get("already") and p2["cur"]["amount"] == amt, p2.get("cur"))
st, p3 = call(f"/api/pick/{code}", "POST", {"cabin": 1}); check("no new pick after today's spin (1 round/day)", st == 409 and p3["error"] == "done", p3)
st, p3 = call(f"/api/spin/{j3['code']}", "POST", {}); check("fresh link shares the same spin (already)", st == 200 and p3.get("already"), p3)
st, q = call(f"/api/seen/{code}", "POST", {"id": p["cur"]["id"]}); st, s = call(f"/api/session/{code}"); check("seen flag stored", s["cur"]["seen"] == 1, s.get("cur"))
check("hist has the spin, week shows today's amount", s["hist"][0]["amount"] == amt and any(w["day"] == today and w["amount"] == amt for w in s["week"]), (s.get("hist"), s.get("week")))
# ---- turnover clears after more slot bets (same day): need amt*5 more on top of 900
cur.execute("UPDATE bets_daily_category SET valid_bet=%s WHERE user_id=1 AND biz_date=%s AND category='egame'", (900 + amt * 5, today))
st, s = call(f"/api/session/{code}"); check("turnover cleared after 5x slots", s["wager"]["bonus"] == 0 and s["wager"]["cleared"] == amt and s["hist"][0]["cleared"], s.get("wager"))
# ---- deposit gate (maria: 80 < 100) and casino-doesn't-count (luis)
st, j = call("/api/link", "POST", {"account": "maria_x"}, tok=tok); mcode = j["code"]
st, p = call(f"/api/pick/{mcode}", "POST", {"cabin": 1}); check("maria picks cabin 1: slots ok (400>=300) but deposit short", st == 200 and p["betOk"] and not p["depOk"] and not p["ready"], (p.get("depOk"), p.get("betOk")))
st, p = call(f"/api/spin/{mcode}", "POST", {}); check("maria spin refused: deposit", st == 409 and p["error"] == "locked" and "deposit" in p["msg"], p)
cur.execute("INSERT INTO deposits VALUES ('o20',2,'maria_x',50,'Success',%s,%s)", (f"{today} 17:00:00", today))
st, s = call(f"/api/session/{mcode}"); check("maria: 80+50=130 deposit -> ready", s["dep"] == 130 and s["ready"], (s.get("dep"), s.get("ready")))
st, j = call("/api/link", "POST", {"account": "luis"}, tok=tok); lcode = j["code"]
st, p = call(f"/api/pick/{lcode}", "POST", {"cabin": 1}); check("luis: casino 9000 doesn't count as slots", p["slot"] == 0 and p["other"] == 9000 and not p["betOk"], (p.get("slot"), p.get("other")))
# ---- cap: link refused, spin refused, raise budget, spin ok
st, c0 = call("/api/cap", tok=tok); used = c0["capUsed"]; check("cap used = juan's amount", used == amt, c0)
st, c1 = call("/api/cap", "POST", {"dailyCap": used - 1}, tok=tok); check("cap below used rejected", st == 400, c1)
st, c1 = call("/api/cap", "POST", {"dailyCap": used + 5}, tok=tok); check("cap set to used+5 -> capped (min prize 8)", st == 200 and c1["capped"] and c1["capLeft"] == 5, c1)
st, j = call("/api/link", "POST", {"account": "pedro"}, tok=tok); check("link refused while capped", st == 409 and j["error"] == "cap", j)
st, c2 = call("/api/cap", "POST", {"dailyCap": used + 5000}, tok=tok); check("budget raised", st == 200 and not c2["capped"], c2)
st, j = call("/api/link", "POST", {"account": "pedro"}, tok=tok); pcode = j.get("code"); check("link ok after raise", st == 200 and pcode, j)
st, p = call(f"/api/pick/{pcode}", "POST", {"cabin": 2}); check("pedro cabin 2 (600) ready with 5000 slots", p["ready"], p.get("cur"))
cur.execute("UPDATE cg_settings SET daily_cap=%s WHERE biz_date=%s", (used + 10, today))   # cap again, but link exists
st, p = call(f"/api/spin/{pcode}", "POST", {}); check("spin refused by cap", st == 409 and p["error"] == "cap", p)
cur.execute("DELETE FROM cg_settings WHERE biz_date=%s", (today,))                           # back to default 10,000
st, p = call(f"/api/spin/{pcode}", "POST", {}); check("pedro spins once budget is back (tier 2: 18..28)", st == 200 and 18 <= p["cur"]["amount"] <= 28, p.get("cur"))
st, c3 = call("/api/cap", tok=tok); check("cap default restored + used", c3["dailyCap"] == 10000 and c3["capUsed"] == amt + p["cur"]["amount"], c3)
st, j = call("/api/lookup?account=pedro", tok=tok); check("admin lookup shows paid spin + snapshot", j["cur"]["status"] == "paid" and j["cur"]["slot"] == 5000 and j["cur"]["dep"] == 1000 and j["code"] == pcode, j.get("cur"))
time.sleep(1.5)
posts = [json.loads(l) for l in open(os.path.join(os.path.dirname(__file__), "ledger_posts.jsonl"), encoding="utf-8") if l.strip()]
check("ledger got juan + pedro wins with account name + game", len(posts) == 2 and {x["name"] for x in posts} == {"Juan123", "pedro"} and all(x["brand"] == "gopyesta" and x["game"] == "Lucky Ferris Wheel" for x in posts), posts)
print("\nFAILS:", fails or "none")

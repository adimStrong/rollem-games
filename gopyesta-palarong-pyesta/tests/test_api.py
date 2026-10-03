"""API-level checks against the locally running app (port 8798) + stub ledger. Run AFTER test_ui.py
(which plays Juan's 2 entries) or on a fresh seed."""
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

st, j = call("/api/admin-login", "POST", {"password": "wrong"}); check("bad password 403", st == 403)
st, j = call("/api/admin-login", "POST", {"password": "testpw"}); tok = j.get("token"); check("login", st == 200 and tok)
st, j = call("/api/lookup?account=Juan123"); check("lookup needs token", st == 403)
st, j = call("/api/lookup?account=juan123", tok=tok)
check("lookup found (case-insensitive)", st == 200 and j["found"] and j["account"] == "Juan123", j)
check("1 deposit = 1 entry: 150 & 250 count, 80 doesn't", j["entriesEarned"] == 2 and len(j["deposits"]) == 3, j.get("deposits"))
check("cumulative reqs 450 / 1200", [e["required"] for e in j["entries"]] == [450, 1200], j.get("entries"))
check("turnover 1300 (fishing excluded) unlocks both", j["wagering"]["validBet"] == 1300 and j["entriesUnlocked"] == 2, j.get("wagering"))
check("name from real_name", j["name"] == "Juan Dela Cruz", j.get("name"))
used_before = j["entriesUsed"]
st, j = call("/api/lookup?account=maria_x", tok=tok)
check("maria: 2 entries, 1 unlocked, 1 locked", j["entriesEarned"] == 2 and j["entriesUnlocked"] == 1 and j["entriesLocked"] == 1 and j["wagering"]["nextRequired"] == 960, j)
st, j = call("/api/lookup?account=tester", tok=tok); check("test account not found", st == 200 and not j["found"], j)
st, j = call("/api/lookup?account=nobody", tok=tok); check("unknown not found", st == 200 and not j["found"])
st, j = call("/api/link", "POST", {"account": "juan123"}, tok=tok); code = j.get("code")
check("link created", st == 200 and code and code.startswith("juan123-"), j)
st, j2 = call("/api/link", "POST", {"account": "juan123"}, tok=tok); check("link reused same day", j2.get("code") == code, j2.get("code"))
st, j3 = call("/api/link", "POST", {"account": "juan123", "fresh": True}, tok=tok); check("fresh link new code", j3.get("code") != code and j3.get("code").startswith("juan123-"))
st, s = call(f"/api/session/{code}"); check("session public GET", st == 200 and s["exists"] and s["name"] == "Juan Dela Cruz" and s["entriesEarned"] == 2, s)
st, s = call("/api/session/nope-0000"); check("unknown session", st == 200 and not s["exists"])
left = 2 - used_before; prizes = []
for i in range(left):
    st, p = call(f"/api/play/{code}", "POST", {})
    check(f"juan play #{used_before+i+1}", st == 200 and p["prize"] in (17, 27, 37) and p["entriesPlayable"] == left - i - 1, p)
    prizes.append(p.get("prize"))
st, p = call(f"/api/play/{code}", "POST", {}); check("3rd play refused no_entries", st == 409 and p["error"] == "no_entries", p)
st, p = call(f"/api/play/{j3['code']}", "POST", {}); check("fresh link shares the same entries (refused)", st == 409 and p["error"] == "no_entries", p)
# ---- turnover gate
st, j = call("/api/link", "POST", {"account": "maria_x"}, tok=tok); mcode = j["code"]
if j["entriesUsed"] == 0:
    st, p = call(f"/api/play/{mcode}", "POST", {}); check("maria entry 1 plays (unlocked)", st == 200 and p["entriesLocked"] == 1 and p["entriesPlayable"] == 0, p)
else:
    print("skip: maria entry 1 already played by test_ui")
st, p = call(f"/api/play/{mcode}", "POST", {}); check("maria entry 2 refused: locked", st == 409 and p["error"] == "locked" and "960" in p["msg"], p)
cur.execute("INSERT INTO bets_daily_category VALUES (2,%s,'casino',600,600,0,5,%s)", (today, f"{today} 16:35:00"))
st, s = call(f"/api/session/{mcode}"); check("session shows unlock after bets sync", s["entriesPlayable"] == 1 and s["wagering"]["validBet"] == 1000, s)
st, p = call(f"/api/play/{mcode}", "POST", {}); check("maria entry 2 plays after turnover", st == 200 and p["entriesPlayable"] == 0, p)
# ---- cap: link refused, play refused, raise budget, play ok
st, c0 = call("/api/cap", tok=tok); used = c0["capUsed"]
st, c1 = call("/api/cap", "POST", {"dailyCap": used - 1}, tok=tok); check("cap below used rejected", st == 400, c1)
st, c1 = call("/api/cap", "POST", {"dailyCap": used + 10}, tok=tok); check("cap set to used+10 -> capped", st == 200 and c1["capped"] and c1["capLeft"] == 10, c1)
st, j = call("/api/link", "POST", {"account": "pedro"}, tok=tok); check("link refused while capped", st == 409 and j["error"] == "cap", j)
st, j = call("/api/lookup?account=pedro", tok=tok); check("lookup still works, shows capped", j["found"] and j["capped"], j.get("capped"))
st, c2 = call("/api/cap", "POST", {"dailyCap": used + 5000}, tok=tok); check("budget raised", st == 200 and not c2["capped"] and c2["dailyCap"] == used + 5000, c2)
st, j = call("/api/link", "POST", {"account": "pedro"}, tok=tok); pcode = j.get("code"); check("link ok after raise", st == 200 and pcode, j)
cur.execute("UPDATE cg_settings SET daily_cap=%s WHERE biz_date=%s", (used + 10, today))   # cap again, but link exists
st, p = call(f"/api/play/{pcode}", "POST", {}); check("play refused by cap", st == 409 and p["error"] == "cap", p)
cur.execute("DELETE FROM cg_settings WHERE biz_date=%s", (today,))                           # back to default 10,000
st, p = call(f"/api/play/{pcode}", "POST", {}); check("pedro plays once budget is back", st == 200, p)
st, c3 = call("/api/cap", tok=tok); check("cap default restored", c3["dailyCap"] == 10000 and c3["capUsed"] == used + p["prize"], c3)
time.sleep(1.5)
posts = [json.loads(l) for l in open(os.path.join(os.path.dirname(__file__), "ledger_posts.jsonl"), encoding="utf-8") if l.strip()]
check("ledger got Juan's 2 wins with account name", len([x for x in posts if x["name"] == "Juan123"]) == 2 and all(x["brand"] == "gopyesta" and x["game"] == "Palarong Pyesta" and x["amount"] in (17, 27, 37) for x in posts), posts)
check("ledger got maria's 2 + pedro's 1", len([x for x in posts if x["name"] == "maria_x"]) == 2 and len([x for x in posts if x["name"] == "pedro"]) == 1, posts)
print("\nFAILS:", fails or "none")

"""API-level checks against the locally running app (port 8798) + stub ledger."""
import json, urllib.request, urllib.error, psycopg2, os, time
B = "http://127.0.0.1:8798"
def call(path, method="GET", body=None, tok=None):
    req = urllib.request.Request(B + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **({"X-Admin-Token": tok} if tok else {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")
fails = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name, info if not cond else "")
    if not cond: fails.append(name)

st, j = call("/api/admin-login", "POST", {"password": "wrong"}); check("bad password 403", st == 403)
st, j = call("/api/admin-login", "POST", {"password": "testpw"}); tok = j.get("token"); check("login", st == 200 and tok)
st, j = call("/api/lookup?account=Juan123"); check("lookup needs token", st == 403)
st, j = call("/api/lookup?account=juan123", tok=tok)
check("lookup found (case-insensitive)", st == 200 and j["found"] and j["account"] == "Juan123", j)
check("window deposits = 150+250 only", j["depositTotal"] == 400 and len(j["deposits"]) == 2, j.get("deposits"))
check("entries earned = 4", j["entriesEarned"] == 4, j.get("entriesEarned"))
check("wagering egame+casino only = 1300 vs 1200 met", j["wagering"]["validBet"] == 1300 and j["wagering"]["required"] == 1200 and j["wagering"]["met"], j.get("wagering"))
check("name from real_name", j["name"] == "Juan Dela Cruz", j.get("name"))
used_before = j["entriesUsed"]
st, j = call("/api/lookup?account=maria_x", tok=tok); check("maria 0 entries (₱80)", st == 200 and j["found"] and j["entriesEarned"] == 0, j)
st, j = call("/api/lookup?account=tester", tok=tok); check("test account not found", st == 200 and not j["found"], j)
st, j = call("/api/lookup?account=nobody", tok=tok); check("unknown not found", st == 200 and not j["found"])
st, j = call("/api/link", "POST", {"account": "juan123"}, tok=tok); code = j.get("code")
check("link created", st == 200 and code and code.startswith("juan123-"), j)
st, j2 = call("/api/link", "POST", {"account": "juan123"}, tok=tok); check("link reused same day", j2.get("code") == code, j2.get("code"))
st, j3 = call("/api/link", "POST", {"account": "juan123", "fresh": True}, tok=tok); check("fresh link new code", j3.get("code") != code and j3.get("code").startswith("juan123-"))
st, s = call(f"/api/session/{code}"); check("session public GET", st == 200 and s["exists"] and s["name"] == "Juan Dela Cruz" and s["entriesEarned"] == 4, s)
st, s = call("/api/session/nope-0000"); check("unknown session", st == 200 and not s["exists"])
left = 4 - used_before
prizes = []
for i in range(left):
    st, p = call(f"/api/play/{code}", "POST", {})
    check(f"play #{used_before+i+1}", st == 200 and p["prize"] in (17, 27, 37) and p["entriesLeft"] == left - i - 1, p)
    prizes.append(p.get("prize"))
st, p = call(f"/api/play/{code}", "POST", {}); check("5th play refused no_entries", st == 409 and p["error"] == "no_entries", p)
st, p = call(f"/api/play/{j3['code']}", "POST", {}); check("fresh link shares the same entries (refused)", st == 409 and p["error"] == "no_entries", p)
# cap: burn the cap with a direct row, give maria an entry, expect 'cap'
c = psycopg2.connect("postgresql://postgres:cgtest@localhost:55432/cg"); c.autocommit = True; cur = c.cursor()
from datetime import datetime; from zoneinfo import ZoneInfo
today = datetime.now(ZoneInfo("Asia/Manila")).strftime("%Y-%m-%d")
burn = 10000 - sum(prizes) - 10  # leaves less than the smallest prize
cur.execute("INSERT INTO cg_plays (code,user_id,account,biz_date,entry_no,step,prize,played_at) VALUES ('x-0000',99,'burn',%s,1,0,%s,0)", (today, burn))
cur.execute("INSERT INTO deposits VALUES ('o8',2,'maria_x',120,'Success',%s,%s)", (f"{today} 14:30:00", today))
st, j = call("/api/link", "POST", {"account": "maria_x"}, tok=tok); mcode = j.get("code"); check("maria now 2 entries (80+120=200)", j.get("entriesEarned") == 2, j.get("entriesEarned"))
st, j = call("/api/lookup?account=maria_x", tok=tok); check("capLeft reported", j["capLeft"] == max(0, 10000 - 9900 - sum(prizes) - 0) or j["capLeft"] >= 0, j.get("capLeft"))
st, p = call(f"/api/play/{mcode}", "POST", {}); check("play refused by daily cap", st == 409 and p["error"] == "cap", p)
cur.execute("DELETE FROM cg_plays WHERE account='burn'")
st, p = call(f"/api/play/{mcode}", "POST", {}); check("maria plays after cap freed", st == 200 and p["entriesLeft"] == 1, p)
time.sleep(1.5)
posts = [json.loads(l) for l in open(os.path.join(os.path.dirname(__file__), "ledger_posts.jsonl"), encoding="utf-8") if l.strip()]
juan = [x for x in posts if x["name"] == "Juan123"]
check("ledger got Juan's 4 wins with account name", len(juan) == 4 and all(x["brand"] == "gopyesta" and x["game"] == "Palarong Pyesta" and x["amount"] in (17, 27, 37) for x in juan), posts)
check("ledger got maria's win", any(x["name"] == "maria_x" for x in posts))
print("\nFAILS:", fails or "none")

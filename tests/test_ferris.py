"""Lucky Ferris Wheel — gate order, the roll, the cap rule, and the real Flask routes.

Runs against tests/fakedb.py (see its docstring for what that does and does not prove).
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

import fakedb

# app.py reads these at import and calls init_db() at import, so the fake has to be in
# place before the import happens.
sys.modules["psycopg2"] = fakedb
sys.modules["psycopg2.extras"] = fakedb.extras
fakedb.extras = fakedb.extras
os.environ.setdefault("DATABASE_URL", "postgres://fake")
os.environ.setdefault("ADMIN_PASSWORD", "adminpw")
os.environ.setdefault("SECRET_KEY", "sekrit")
os.environ.setdefault("TZ", "Asia/Manila")

import app as A

DAY = A.today()
failures = []


def check(name, cond, detail=""):
    line = ("  ok   " if cond else "  FAIL ") + name + (f"  -- {detail}" if detail and not cond else "")
    print(line.replace("₱", "P"))
    if not cond:
        failures.append(name)


def fresh(deposit=0, turnover=0, cabin=None, played=False, cap=None):
    fakedb.reset()
    fakedb.add_user(7, "laus87", "Juan Dela Cruz")
    fakedb.STATE["sessions"]["laus87-ab12"] = {
        "code": "laus87-ab12", "user_id": 7, "account": "laus87",
        "name": "Juan Dela Cruz", "biz_date": DAY, "created_at": 1}
    if deposit:
        fakedb.add_deposit(7, DAY, deposit, at="14:00")
    if turnover:
        fakedb.set_turnover(7, DAY, turnover)
    if cabin:
        fakedb.STATE["picks"][(7, DAY)] = {"cabin": cabin, "tier": A.tier_for_cabin(cabin)}
    if played:
        fakedb.STATE["plays"].append({"code": "laus87-ab12", "user_id": 7, "account": "laus87",
                                      "biz_date": DAY, "entry_no": 1, "step": (cabin or 1) - 1,
                                      "prize": 14, "tier": A.tier_for_cabin(cabin or 1),
                                      "played_at": 1})
    if cap is not None:
        fakedb.STATE["settings"][DAY] = cap


A.app.config["TESTING"] = True
cli = A.app.test_client()
PLAY = "/api/play/laus87-ab12"
PICK = "/api/ferris/pick/laus87-ab12"
SESS = "/api/session/laus87-ab12"

print("\n-- cabins and tiers")
check("8 cabins", A.N_CABINS == 8)
check("cabins pair onto 4 tiers",
      [A.tier_for_cabin(c) for c in range(1, 9)] == [1, 2, 3, 4, 1, 2, 3, 4])
check("cabin 0 and 9 are rejected", A.tier_for_cabin(0) == 0 and A.tier_for_cabin(9) == 0)
check("junk cabin is rejected, not crashed",
      A.tier_for_cabin(None) == 0 and A.tier_for_cabin("x") == 0)
check("requirements match the design file",
      [A.TIERS[t][0] for t in (1, 2, 3, 4)] == [300, 600, 8000, 50000])
check("ranges match the design file",
      [A.TIERS[t][1:] for t in (1, 2, 3, 4)] == [(8, 18), (18, 28), (18, 188), (288, 888)])

print("\n-- the roll stays inside its tier")
for t in (1, 2, 3, 4):
    _r, lo, hi = A.TIERS[t]
    rolls = [A.draw_prize(t) for _ in range(4000)]
    check(f"tier {t} within P{lo}-P{hi}", all(lo <= x <= hi for x in rolls),
          f"min={min(rolls)} max={max(rolls)}")
    check(f"tier {t} reaches both ends", min(rolls) == lo and max(rolls) == hi)
check("unknown tier pays nothing", A.draw_prize(99) == 0)

print("\n-- config never leaks the reward ranges")
cfg = cli.get("/api/config").get_json()
blob = str(cfg)
check("requirements are sent", cfg["tierRequired"]["4"] == 50000)
check("no ceiling in the payload", "888" not in blob and "188" not in blob, blob[:160])
check("no prize table any more", "prizes" not in cfg and "weights" not in cfg)

print("\n-- picking")
fresh()
r = cli.post(PICK, json={"cabin": 99})
check("a cabin off the wheel is a 400", r.status_code == 400
      and r.get_json()["error"] == "bad_cabin")
r = cli.post(PICK, json={"cabin": 3})
check("cabin 3 locks", r.status_code == 200 and r.get_json()["pick"]["cabin"] == 3)
check("and resolves to tier 3", r.get_json()["pick"]["tier"] == 3)
r = cli.post(PICK, json={"cabin": 1})
j = r.get_json()
check("switching to the cheap cabin is refused",
      j["lockedElsewhere"] is True and j["pick"]["cabin"] == 3, str(j.get("pick")))
r = cli.post("/api/ferris/pick/nope-zz99", json={"cabin": 1})
check("an unknown link cannot pick", r.status_code == 404)

print("\n-- the gate, in order")
fresh(cabin=3)
r = cli.post(PLAY)
check("no deposit -> refused", r.status_code == 409
      and r.get_json()["error"] == "no_entries")

fresh(deposit=50, cabin=3)
r = cli.post(PLAY)
check("a deposit under P100 does not qualify the day",
      r.status_code == 409 and r.get_json()["error"] == "no_entries")

fresh(deposit=500, cabin=3)
r = cli.post(PLAY)
check("deposit but no turnover -> locked", r.status_code == 409
      and r.get_json()["error"] == "locked")
check("the message names the shortfall", "8,000" in r.get_json()["msg"], r.get_json()["msg"])

fresh(deposit=500, turnover=5000, cabin=3)
r = cli.post(PLAY)
check("turnover under the cabin's bar -> locked", r.get_json()["error"] == "locked")

fresh(deposit=500, turnover=9000)
r = cli.post(PLAY)
check("turnover met but no cabin picked -> refused",
      r.status_code == 409 and r.get_json()["error"] == "no_pick")

print("\n-- failing closed")
fresh(deposit=500, turnover=999999, cabin=3)
fakedb.STATE["fail_turnover"] = True
r = cli.post(PLAY)
j = r.get_json()
check("an unreadable turnover table pays nothing", j["error"] == "locked", str(j)[:120])
check("and says so rather than blaming the player",
      "mabasa" in j["msg"], j["msg"])

print("\n-- a met goal pays, once")
fresh(deposit=500, turnover=9000, cabin=3)
r = cli.post(PLAY)
j = r.get_json()
check("met goal pays", r.status_code == 200 and j["ok"] is True, str(j)[:140])
check("amount is inside tier 3", 18 <= j["prize"] <= 188, str(j.get("prize")))
check("cabin comes back", j["cabin"] == 3 and j["tier"] == 3)
check("wager need is the multiple of the bonus",
      j["wagerNeed"] == j["prize"] * A.WAGER_MULT)
first = j["prize"]
r2 = cli.post(PLAY)
j2 = r2.get_json()
check("a second tap replays, never re-rolls",
      j2.get("replay") is True and j2["prize"] == first, str(j2)[:140])
check("exactly one row was written", len(fakedb.STATE["plays"]) == 1,
      str(len(fakedb.STATE["plays"])))
check("the row is entry_no 1, so the unique index is what holds the once-a-day rule",
      fakedb.STATE["plays"][0]["entry_no"] == 1)
check("the row stores the cabin and tier",
      fakedb.STATE["plays"][0]["step"] == 2 and fakedb.STATE["plays"][0]["tier"] == 3)

print("\n-- the daily cap")
# turnover 100 against tier 1's 300: the goal is genuinely NOT met
fresh(deposit=500, turnover=100, cabin=1, cap=100)
fakedb.STATE["plays"].append({"code": "x", "user_id": 99, "account": "someone",
                              "biz_date": DAY, "entry_no": 1, "step": 0, "prize": 100,
                              "tier": 1, "played_at": 1})
r = cli.post(PLAY)
j = r.get_json()
check("cap turns away a player who has NOT met the goal", j["error"] == "cap", str(j)[:120])
check("and does not claim the goal carries over",
      "bukas" in j["msg"].lower(), j["msg"])

fresh(deposit=500, turnover=5000, cabin=1, cap=100)
fakedb.STATE["plays"].append({"code": "x", "user_id": 99, "account": "someone",
                              "biz_date": DAY, "entry_no": 1, "step": 0, "prize": 100,
                              "tier": 1, "played_at": 1})
r = cli.post(PLAY)
j = r.get_json()
check("cap still pays a player who HAS met the goal",
      r.status_code == 200 and j.get("ok") is True and 8 <= j["prize"] <= 18, str(j)[:140])

print("\n-- expiry and closing time")
fresh(deposit=500, turnover=9000, cabin=3)
fakedb.STATE["sessions"]["laus87-ab12"]["biz_date"] = "2020-01-01"
r = cli.post(PLAY)
check("yesterday's link cannot play", r.status_code == 409
      and r.get_json()["error"] == "expired")
r = cli.get(SESS)
check("and the session reports it expired", r.get_json()["expired"] is True)

print("\n-- the session payload")
fresh(deposit=500, turnover=5000, cabin=3)
s = cli.get(SESS).get_json()
check("session exists", s["exists"] is True and s["account"] == "laus87")
check("carries the locked cabin", s["pick"]["cabin"] == 3)
check("carries the requirement", s["required"] == 8000)
check("carries deposit and turnover", s["depositTotal"] == 500 and s["turnover"] == 5000)
check("goalMet is false while short", s["goalMet"] is False)
check("no reward range in the session payload",
      "888" not in str(s) and "188" not in str(s), str(s)[:200])
r = cli.get("/api/session/nope-zz99")
check("an unknown code is not a crash", r.status_code == 200
      and r.get_json()["exists"] is False)

print("\n-- admin link maker still works on the new game")
fresh(deposit=500, turnover=5000, cabin=3)
tok = cli.post("/api/admin-login", json={"password": "adminpw"}).get_json()["token"]
H = {"X-Admin-Token": tok}
check("wrong password is refused",
      cli.post("/api/admin-login", json={"password": "nope"}).status_code == 403)
check("lookup needs the token", cli.get("/api/lookup?account=laus87").status_code == 403)
l = cli.get("/api/lookup?account=laus87", headers=H).get_json()
check("lookup finds the player", l["found"] is True and l["account"] == "laus87")
check("lookup keeps the entries contract the admin page renders",
      l["entriesEarned"] == 1 and l["entriesUnlocked"] == 0 and l["entriesUsed"] == 0)
check("lookup carries the ferris detail too",
      l["pick"]["cabin"] == 3 and l["required"] == 8000)
mk = cli.post("/api/link", json={"account": "laus87"}, headers=H).get_json()
check("link maker issues a code", bool(mk.get("code")) and mk["code"].startswith("laus87-"))
cap = cli.post("/api/cap", json={"dailyCap": 5000}, headers=H).get_json()
check("cap can be set", cap["dailyCap"] == 5000)
low = cli.post("/api/cap", json={"dailyCap": -1}, headers=H)
check("a cap below what is already awarded is refused", low.status_code == 400)

print("\n-- the pages")
page = cli.get("/").data.decode("utf-8")
check("/ serves the ferris wheel", "Lucky Ferris Wheel" in page or "wheelbox" in page)
check("/ talks to this backend",
      "/api/session/" in page and "/api/ferris/pick/" in page and "/api/play/" in page)
import re as _re
_js = page.split("<script>", 1)[1].rsplit("</script>", 1)[0]
_code = _re.sub(r"/\*.*?\*/", "", _js, flags=_re.S)
_code = _re.sub(r"(?m)^\s*//.*$", "", _code)
check("/ keeps no player state in the browser", "localStorage" not in _code)
check("/ ships no reward range", "888" not in _code and "188" not in _code)
check("/ has no client-side roll", "drawStep" not in _code and "function roll(" not in _code)
check("/#admin redirects to the link maker", "/admin.html#admin" in page)
adm = cli.get("/admin.html").data.decode("utf-8")
check("the link maker is still served", "Link maker" in adm)
# The dead Palosebo demo still sits in this file, so the check is on what the ADMIN sees
# and on the message the team copies to players — not on the file containing the string.
check("the link maker is pinned to admin mode", 'let mode="admin"' in adm)
check("the copy-to-player message describes the ferris wheel",
      "Lucky Ferris Wheel" in adm and "akyat sa palosebo" not in adm)
check("the admin blurb no longer says 1 palo / 3x turnover",
      "= 1 palo</b>" not in adm and "3× turnover sa slots/casino" not in adm)
# The link maker and the game are two files now, so a link built from location.href would
# hand every player a link to /admin.html instead of the game.
check("the player link points at the game, not the admin page",
      'location.origin+"/#"+look.code' in adm and 'location.href.split("#")[0]+"#"' not in adm)
check("the admin does not build the dead Palosebo booth",
      'if (mode !== "admin") buildView();' in adm)
check("the admin hides the stale player preview",
      '$("previewLabel").hidden=true' in adm)
check("the armed-state transition fix is in the game page",
      "transition:none;animation:wiggle" in page)
check("art is served from this service's root",
      "/ferris-logo.png" in page and "/ferris-bg.jpg" in page)
check("logo and background resolve",
      cli.get("/ferris-logo.png").status_code == 200
      and cli.get("/ferris-bg.jpg").status_code == 200)

print()
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    sys.exit(1)
print("all ferris tests passed")

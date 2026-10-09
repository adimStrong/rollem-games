"""Lucky Ferris Wheel — the mechanics are Palarong Pyesta's, unchanged.

So most of what is asserted here is that the RULES still behave exactly as they did
before the game was reskinned: one qualifying deposit in the window = one entry, each
entry unlocks at WAGER_MULT x the cumulative deposits up to it, the prize is drawn
server-side from PRIZES/WEIGHTS, the daily cap holds, and entries cannot be replayed.
The rest covers the page split (game at /, link maker at /admin.html).

Runs against tests/fakedb.py — see its docstring for what that cannot prove.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

import fakedb

sys.modules["psycopg2"] = fakedb
sys.modules["psycopg2.extras"] = fakedb.extras
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


def fresh(deposits=(), turnover=0, cap=None, plays=()):
    """deposits: list of (amount, "HH:MM")"""
    fakedb.reset()
    fakedb.add_user(7, "laus87", "Juan Dela Cruz")
    fakedb.STATE["sessions"]["laus87-ab12"] = {
        "code": "laus87-ab12", "user_id": 7, "account": "laus87",
        "name": "Juan Dela Cruz", "biz_date": DAY, "created_at": 1}
    for amt, at in deposits:
        fakedb.add_deposit(7, DAY, amt, at=at)
    if turnover:
        fakedb.set_turnover(7, DAY, turnover)
    if cap is not None:
        fakedb.STATE["settings"][DAY] = cap
    for i, prize in enumerate(plays, 1):
        fakedb.STATE["plays"].append({"code": "laus87-ab12", "user_id": 7, "account": "laus87",
                                      "biz_date": DAY, "entry_no": i, "step": 1,
                                      "prize": prize, "tier": None, "played_at": 1})


A.app.config["TESTING"] = True
cli = A.app.test_client()
PLAY = "/api/play/laus87-ab12"
SESS = "/api/session/laus87-ab12"
IN = "14:00"   # inside the 1 PM - 9 PM deposit window

print("\n-- the mechanics are the ones that were already live")
check("game renamed", A.GAME_NAME == "Lucky Ferris Wheel")
check("minimum deposit still P100", A.MIN_DEPOSIT == 100)
check("prize table still 37/27/17", A.PRIZES == [37, 27, 17])
check("weights still 5/85/10", A.WEIGHTS == [5, 85, 10])
check("turnover gate still 3x", A.WAGER_MULT == 3)
check("still slots + casino", A.WAGER_CATS == ["egame", "casino"])
check("daily cap still P10,000", A.DAILY_CAP == 10000)
check("deposit window still 1 PM - 9 PM", A.DEP_FROM == "13:00" and A.DEP_TO == "21:00")
check("no cabin/tier rules were introduced",
      not hasattr(A, "CAB_TIER") and not hasattr(A, "TIERS"))

print("\n-- the server still draws the prize")
steps = [A.draw_step() for _ in range(6000)]
check("every step is a real placement", set(steps) <= {0, 1, 2}, str(sorted(set(steps))))
check("all three placements occur", set(steps) == {0, 1, 2})
mid = steps.count(1) / len(steps)
check("the 85% placement dominates", 0.80 < mid < 0.90, f"{mid:.2%}")

print("\n-- entries come from qualifying deposits in the window")
fresh(deposits=[(500, IN)])
s = cli.get(SESS).get_json()
check("one qualifying deposit = one entry", s["entriesEarned"] == 1, str(s["entriesEarned"]))
fresh(deposits=[(500, IN), (300, "15:00"), (50, "16:00")])
s = cli.get(SESS).get_json()
check("a deposit under P100 earns nothing", s["entriesEarned"] == 2, str(s["entriesEarned"]))
fresh(deposits=[(500, "09:00"), (500, "22:00")])
s = cli.get(SESS).get_json()
check("deposits outside the window earn nothing", s["entriesEarned"] == 0, str(s["entriesEarned"]))
fresh(deposits=[(9999, IN)])
s = cli.get(SESS).get_json()
check("a big deposit is still only one entry", s["entriesEarned"] == 1)

print("\n-- the 3x cumulative turnover gate")
fresh(deposits=[(500, IN)], turnover=0)
r = cli.post(PLAY)
check("no turnover -> locked", r.status_code == 409 and r.get_json()["error"] == "locked")
check("the message names what is needed", "1,500" in r.get_json()["msg"], r.get_json()["msg"])

fresh(deposits=[(500, IN)], turnover=1499)
check("just under 3x is still locked",
      cli.post(PLAY).get_json()["error"] == "locked")
fresh(deposits=[(500, IN)], turnover=1500)
s = cli.get(SESS).get_json()
check("exactly 3x unlocks", s["entriesPlayable"] == 1, str(s))

# two deposits: entry 2 needs 3x the CUMULATIVE total, not 3x its own amount
fresh(deposits=[(500, IN), (500, "15:00")], turnover=1500)
s = cli.get(SESS).get_json()
check("entry 1 unlocked, entry 2 still locked on cumulative",
      s["entriesEarned"] == 2 and s["entriesUnlocked"] == 1 and s["entriesLocked"] == 1, str(s))
check("the next requirement is 3x the cumulative P1,000",
      s["wagering"]["nextRequired"] == 3000, str(s["wagering"]))
fresh(deposits=[(500, IN), (500, "15:00")], turnover=3000)
s = cli.get(SESS).get_json()
check("3x cumulative unlocks both", s["entriesUnlocked"] == 2, str(s))

print("\n-- failing closed when turnover cannot be read")
fresh(deposits=[(500, IN)], turnover=999999)
fakedb.STATE["fail_turnover"] = True
r = cli.post(PLAY)
check("an unreadable category table pays nothing",
      r.status_code == 409 and r.get_json()["error"] == "locked", str(r.get_json())[:120])

print("\n-- playing consumes one entry")
fresh(deposits=[(500, IN), (500, "15:00")], turnover=3000)
r = cli.post(PLAY)
j = r.get_json()
check("a spin pays", r.status_code == 200 and j["ok"] is True, str(j)[:140])
check("the prize is from the table", j["prize"] in A.PRIZES, str(j.get("prize")))
check("it is entry 1", j["entryNo"] == 1)
check("one entry remains", j["entriesPlayable"] == 1, str(j))
r2 = cli.post(PLAY).get_json()
check("the second spin is entry 2", r2["entryNo"] == 2)
check("entries are now used up", r2["entriesPlayable"] == 0)
r3 = cli.post(PLAY)
check("a third spin is refused", r3.status_code == 409
      and r3.get_json()["error"] == "no_entries")
check("exactly two rows were written", len(fakedb.STATE["plays"]) == 2,
      str(len(fakedb.STATE["plays"])))
check("the rows are entry_no 1 and 2",
      [p["entry_no"] for p in fakedb.STATE["plays"]] == [1, 2])

print("\n-- the daily cap")
fresh(deposits=[(500, IN)], turnover=1500, cap=10)
r = cli.post(PLAY)
check("a prize that would exceed the cap is refused",
      r.status_code == 409 and r.get_json()["error"] == "cap", str(r.get_json())[:120])
check("and nothing was recorded", len(fakedb.STATE["plays"]) == 0)

print("\n-- closing time and expiry")
fresh(deposits=[(500, IN)], turnover=1500)
fakedb.STATE["sessions"]["laus87-ab12"]["biz_date"] = "2020-01-01"
r = cli.post(PLAY)
check("yesterday's link cannot play", r.status_code == 409
      and r.get_json()["error"] == "expired")
check("and the session says expired", cli.get(SESS).get_json()["expired"] is True)
r = cli.post("/api/play/nope-zz99")
check("an unknown link cannot play", r.status_code == 404)
check("an unknown code is not a crash",
      cli.get("/api/session/nope-zz99").get_json()["exists"] is False)

print("\n-- the session payload")
fresh(deposits=[(500, IN)], turnover=1500)
s = cli.get(SESS).get_json()
check("carries the deposit total the page shows", s["depositTotal"] == 500, str(s.get("depositTotal")))
check("carries turnover", s["wagering"]["validBet"] == 1500)
check("carries the config", s["config"]["prizes"] == [37, 27, 17])

print("\n-- admin link maker")
fresh(deposits=[(500, IN)], turnover=1500)
tok = cli.post("/api/admin-login", json={"password": "adminpw"}).get_json()["token"]
H = {"X-Admin-Token": tok}
check("wrong password refused",
      cli.post("/api/admin-login", json={"password": "nope"}).status_code == 403)
check("lookup needs the token", cli.get("/api/lookup?account=laus87").status_code == 403)
l = cli.get("/api/lookup?account=laus87", headers=H).get_json()
check("lookup still returns the entries contract the page renders",
      l["entriesEarned"] == 1 and l["entriesPlayable"] == 1 and "entries" in l)
mk = cli.post("/api/link", json={"account": "laus87"}, headers=H).get_json()
check("link maker issues a code", mk.get("code", "").startswith("laus87-"))
check("cap can be raised", cli.post("/api/cap", json={"dailyCap": 5000},
                                    headers=H).get_json()["dailyCap"] == 5000)

print("\n-- the pages")
page = cli.get("/").data.decode("utf-8")
adm = cli.get("/admin.html").data.decode("utf-8")
import re as _re
_js = page.split("<script>", 1)[1].rsplit("</script>", 1)[0]
_code = _re.sub(r"/\*.*?\*/", "", _js, flags=_re.S)
_code = _re.sub(r"(?m)^\s*//.*$", "", _code)

check("/ serves the ferris wheel", "wheelbox" in page and "Lucky Ferris Wheel" in page)
check("/ talks to the existing API", "/api/session/" in _code and "/api/play/" in _code)
check("/ keeps no player state in the browser", "localStorage" not in _code)
check("/ decides no prize in the browser",
      "drawStep" not in _code and "function roll(" not in _code)
check("/ carries no cabin/tier rules from the design file",
      "CAB_TIER" not in _code and "tierRequired" not in _code)
check("/ does not ship a prize the server did not send",
      "888" not in _code and "188" not in _code)
check("/#admin redirects to the link maker", "/admin.html#admin" in _code)
check("the link maker is served", "Link maker" in adm)
check("the link maker is pinned to admin mode", 'let mode="admin"' in adm)
check("the player link points at the game, not the admin page",
      'location.origin+"/#"+look.code' in adm)
# Not a performance fix — the earlier "it froze the renderer" reading was a hidden
# browser window throttling rAF, not the page. This stands on its own: the admin page
# hides that booth, so building it is pure dead work and a stale view of another game.
check("the admin does not build the dead Palosebo booth",
      'if (mode !== "admin") buildView();' in adm)
check("the admin hides the stale player preview", '$("previewLabel").hidden=true' in adm)
check("the copy-to-player message is about the wheel",
      "Lucky Ferris Wheel" in adm and "akyat sa palosebo" not in adm)
check("the admin still states the real mechanics",
      "3×" in adm and "1 ikot" in adm)
check("art resolves", cli.get("/ferris-logo.png").status_code == 200
      and cli.get("/ferris-bg.jpg").status_code == 200)

print("\n-- the T&C gate carried over from the game this replaces")
check("the player page shows the T&C", 'class="tnc"' in page and "Terms &amp; Conditions" in page)
check("the T&C describes the wheel, not Palosebo",
      "one spin of the wheel" in page and "greased" not in page and "climber" not in page)
check("the T&C still states the real rules",
      "3× the deposit behind it" in page and "₱10,000" in page)
check("there is an agreement box", 'id="agree"' in page and 'id="agreeLbl"' in page)
check("the spin is gated on it", "if(needAgree())return;" in _code)
check("the gate is checked before the request, so it cannot burn an entry",
      _code.index("if(needAgree())return;") < _code.index('api("/api/play/'))
check("the admin T&C matches the player T&C",
      "one spin of the wheel" in adm and "greased" not in adm)

check("no stray control characters in the page",
      not [c for c in page if ord(c) < 9 or 11 <= ord(c) < 32])
check("the T&C disclosure markers render",
      'content:"▸ "' in page and 'content:"▾ "' in page)

print()
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    sys.exit(1)
print("all ferris tests passed")

"""API assertions against a running app.py (see tests/README.md for the full recipe).
Run AFTER fixture.py has seeded the DB and app.py + ledger_stub.py are both up."""
import json
import os
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8798"
ADMIN_PASS = "testpw"
LEDGER_LOG = os.path.join(os.path.dirname(__file__), "ledger_posts.jsonl")

passed = failed = 0


def check(label, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print("OK  ", label)
    else:
        failed += 1
        print("FAIL", label, extra)


def req(method, path, body=None, token=None, expect_any_status=False):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Admin-Token"] = token
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(r, timeout=10)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if expect_any_status:
            return e.code, json.loads(e.read())
        raise


def admin_token():
    status, j = req("POST", "/api/admin-login", {"password": ADMIN_PASS})
    check("admin login succeeds", status == 200 and "token" in j)
    return j["token"]


def main():
    token = admin_token()

    status, j = req("POST", "/api/admin-login", {"password": "wrong"}, expect_any_status=True)
    check("admin login rejects wrong password", status == 403)

    # ---- config shape ----
    status, cfg = req("GET", "/api/config")
    check("config has fixed prize ladder", cfg.get("prizes") == [
        {"amt": 17, "p": 85}, {"amt": 27, "p": 10}, {"amt": 37, "p": 5}, {"amt": 77, "p": 0}], cfg)
    check("config minDeposit=100", cfg.get("minDeposit") == 100, cfg)
    check("config turnover=3", cfg.get("turnover") == 3, cfg)
    check("config wagerCats includes casino", "casino" in cfg.get("wagerCats", []), cfg)
    check("config window is 13:00-21:00", cfg.get("depFrom") == "13:00" and cfg.get("depTo") == "21:00", cfg)
    check("config cabins=8", cfg.get("cabins") == 8, cfg)

    # ---- juan123: eligible (dep 250 in-window, turnover 1300 >= 3*250=750) ----
    status, j = req("GET", "/api/lookup?account=juan123", token=token)
    check("lookup finds juan123", status == 200 and j.get("found"), j)
    check("juan123 dep_total excludes out-of-window/Failed deposits (only the 250 counts)", j["dep"] == 250, j)
    check("juan123 depOk", j["depOk"] is True, j)
    check("juan123 betOk (1300 >= 750)", j["betOk"] is True, j)
    check("juan123 slot excludes fishing category", j["slotToday"] == 1300, j)

    status, j = req("POST", "/api/link", {"account": "juan123"}, token=token)
    check("link created for juan123", status == 200 and j.get("code"), j)
    code1 = j["code"]

    status, j = req("GET", f"/api/session/{code1}")
    check("session exists for juan123's code", j.get("exists") is True, j)
    check("session not ready before a cabin is picked", j["ready"] is False, j)

    status, j = req("POST", f"/api/pick/{code1}", {"cabin": 3})
    check("pick cabin 3 succeeds", status == 200 and j["cur"]["cabin"] == 3, j)
    check("picking a cabin does not change eligibility (still 3x of same deposit)", j["ready"] is True, j)

    status, j = req("POST", f"/api/spin/{code1}")
    check("spin succeeds for eligible juan123", status == 200 and j.get("spun") is True, j)
    amount1 = j["cur"]["amount"]
    check("drawn amount is one of the live ladder values", amount1 in (17, 27, 37), j)
    check("cabin stayed 3 (cosmetic, unaffected by the draw)", j["cur"]["cabin"] == 3, j)

    status, j = req("POST", f"/api/spin/{code1}")
    check("second spin same day is refused as already-played", status == 200 and j.get("already") is True, j)

    status, j = req("POST", f"/api/pick/{code1}", {"cabin": 5}, expect_any_status=True)
    check("re-picking after the round is paid is refused (done)", status == 409 and j.get("error") == "done", j)

    # ---- odds distribution over many trials (fresh accounts each time to bypass 1-spin-per-day) ----
    import random
    import string

    def seed_once(uid, account, amount, dep_hhmm="13:30", bet=5000):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        import psycopg2
        tz = ZoneInfo("Asia/Manila")
        today = datetime.now(tz).strftime("%Y-%m-%d")
        conn = psycopg2.connect("postgresql://postgres:cgtest@localhost:55432/cg")
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("INSERT INTO users (user_id, account, real_name, is_test) VALUES (%s,%s,%s,0) ON CONFLICT (user_id) DO NOTHING",
                    (uid, account, account))
        cur.execute("INSERT INTO deposits VALUES (%s,%s,%s,%s,'Success',%s,%s)",
                    (f"odds-{uid}", uid, account, amount, f"{today} {dep_hhmm}:00", today))
        cur.execute("""INSERT INTO bets_daily_category (user_id,biz_date,category,valid_bet,bet_amount,win_loss,bet_count,updated_at)
                       VALUES (%s,%s,'egame',%s,%s,0,10,%s) ON CONFLICT (user_id,biz_date,category) DO UPDATE SET valid_bet=EXCLUDED.valid_bet""",
                    (uid, today, bet, bet, f"{today} 16:00:00"))
        conn.close()

    counts = {17: 0, 27: 0, 37: 0, 77: 0}
    trials = 200
    base_uid = 1000
    for i in range(trials):
        uid = base_uid + i
        acct = "odds" + "".join(random.choices(string.ascii_lowercase, k=6)) + str(i)
        seed_once(uid, acct, 100, bet=1000)  # dep 100 -> need 300; turnover 1000 >= 300 -> eligible
        s, j = req("POST", "/api/link", {"account": acct}, token=token)
        code = j["code"]
        req("POST", f"/api/pick/{code}", {"cabin": 1})
        s, j = req("POST", f"/api/spin/{code}")
        if s == 200 and j.get("spun"):
            counts[j["cur"]["amount"]] += 1
        elif j.get("error") == "cap":
            break  # ran into the daily cap partway through; stop, the distribution sample is just smaller

    total = sum(counts.values())
    check(f"odds sample drew {total}/{trials} spins before any cap hit", total >= 50, counts)
    if total >= 50:
        p17 = counts[17] / total
        check(f"~85% draw rate for ₱17 (got {p17:.0%})", 0.70 <= p17 <= 0.97, counts)
        check("₱77 (0% weight) never drawn", counts[77] == 0, counts)

    # ---- maria_x: turnover-locked ----
    status, j = req("GET", "/api/lookup?account=maria_x", token=token)
    check("maria_x depOk", j["depOk"] is True, j)
    check("maria_x betOk is False (200 < 450 needed)", j["betOk"] is False, j)
    status, j = req("POST", "/api/link", {"account": "maria_x"}, token=token)
    code2 = j["code"]
    req("POST", f"/api/pick/{code2}", {"cabin": 1})
    status, j = req("POST", f"/api/spin/{code2}", expect_any_status=True)
    check("spin refused while turnover-locked", status == 409 and j.get("error") == "locked", j)

    # ---- tester (is_test) excluded ----
    status, j = req("GET", "/api/lookup?account=tester", token=token)
    check("is_test account not found via lookup", j.get("found") is False, j)

    # ---- unauthenticated admin calls rejected ----
    status, j = req("GET", "/api/lookup?account=pedro", expect_any_status=True)
    check("lookup without admin token is forbidden", status == 403, j)
    status, j = req("POST", "/api/link", {"account": "pedro"}, expect_any_status=True)
    check("link without admin token is forbidden", status == 403, j)

    # ---- daily cap refusal via /api/cap ----
    status, j = req("GET", "/api/cap", token=token)
    used_before = j["capUsed"]
    status, j = req("POST", "/api/cap", {"dailyCap": used_before}, token=token)
    check("cap set to current usage", status == 200 and j["capped"] is True, j)
    status, j = req("POST", "/api/link", {"account": "pedro"}, token=token, expect_any_status=True)
    check("link refused once the daily cap is exhausted", status == 409 and j.get("error") == "cap", j)
    # restore a generous cap so later manual poking doesn't trip over this
    req("POST", "/api/cap", {"dailyCap": 1_000_000}, token=token)

    # ---- ledger got exactly the win posts we expect (amount in {17,27,37}, never 77) ----
    time.sleep(0.3)
    with open(LEDGER_LOG, encoding="utf-8") as f:
        posts = [json.loads(line) for line in f if line.strip()]
    gopyesta_posts = [p for p in posts if p.get("brand") == "gopyesta"]
    check("wins-ledger received at least the juan123 + odds-sample posts", len(gopyesta_posts) >= 1 + total, len(gopyesta_posts))
    check("every posted amount is a live ladder value", all(p["amount"] in (17, 27, 37) for p in gopyesta_posts),
          [p["amount"] for p in gopyesta_posts if p["amount"] not in (17, 27, 37)])

    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()

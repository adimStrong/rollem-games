"""Gopyesta · Palarong Pyesta (Palosebo) — backend-verified community game.

Reads the Gopyesta platform Postgres (deposits / users / bets_daily_category, filled by the
gopyesta-retention pullers), turns today's real deposits into game entries, gates each entry
behind the player's real slots+casino turnover, draws every prize SERVER-SIDE, enforces the
daily bonus budget, and records every win in the shared wins-ledger.

Mechanics (whiteboard "GPT2027 — Community Game Mechanics", Gopyesta column, as confirmed 2026-10-03):
  * ONE Success deposit of >= ₱100 made 1 PM–9 PM today = ONE entry (palo), whatever the amount
  * an entry is LOCKED until the player's slots (egame) + casino valid bet today reaches
    3× the cumulative qualifying deposits up to that entry (deposits unlock in time order)
  * prize is the climbing race's finishing place, drawn server-side: 1st ₱37 (5%) · 2nd ₱27 (85%) · 3rd ₱17 (10%)
  * ₱10,000 bonus budget per day across all players; when reached, no new links and no plays —
    the admin can raise today's budget (stored per day in cg_settings)
  * unplayed / still-locked entries expire at the end of the day (PLAY_UNTIL)
  * payout is a manual GCash send tracked in wins-ledger (Paid / Revoke)

Tables it OWNS in that database (created on boot, prefixed cg_): cg_sessions, cg_plays, cg_settings.
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg2
import psycopg2.extras
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder=None)

DATABASE_URL = os.environ["DATABASE_URL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
SECRET_KEY = os.environ["SECRET_KEY"]
LEDGER_URL = os.environ.get("LEDGER_URL", "https://wins-ledger-production.up.railway.app/api/win")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
TZ = ZoneInfo(os.environ.get("TZ", "Asia/Manila"))

# ---- mechanics (env-overridable so the numbers can be tuned without a code change) ----
BRAND = "gopyesta"
GAME_NAME = "Palarong Pyesta"
MIN_DEPOSIT = int(os.environ.get("MIN_DEPOSIT", os.environ.get("ENTRY_PESO", "100")))  # one deposit >= this = one entry
PRIZES = [int(x) for x in os.environ.get("PRIZES", "37,27,17").split(",")]  # [1st, 2nd, 3rd] place prize
WEIGHTS = [int(x) for x in os.environ.get("WEIGHTS", "5,85,10").split(",")]  # win rate per placement
DAILY_CAP = int(os.environ.get("DAILY_CAP", "10000"))
WAGER_MULT = float(os.environ.get("WAGER_MULT", "3"))   # 0 = no turnover gate
WAGER_CATS = [c.strip() for c in os.environ.get("WAGER_CATS", "egame,casino").split(",") if c.strip()]
DEP_FROM = os.environ.get("DEP_FROM", "13:00")   # deposits counted from (inclusive, HH:MM)
DEP_TO = os.environ.get("DEP_TO", "21:00")       # deposits counted until (exclusive)
PLAY_UNTIL = os.environ.get("PLAY_UNTIL", "23:59")  # entries playable until this time, same day
assert len(PRIZES) == len(WEIGHTS) and sum(WEIGHTS) == 100
MIN_PRIZE = min(p for p, w in zip(PRIZES, WEIGHTS) if w > 0)

CONFIG = {
    "brand": BRAND, "game": GAME_NAME, "minDeposit": MIN_DEPOSIT, "prizes": PRIZES, "weights": WEIGHTS,
    "dailyCap": DAILY_CAP, "wagerMult": WAGER_MULT, "wagerCats": WAGER_CATS,
    "depFrom": DEP_FROM, "depTo": DEP_TO, "playUntil": PLAY_UNTIL,
}


# ---------------------------------------------------------------- helpers
def now():
    return datetime.now(TZ)


def today():
    return now().strftime("%Y-%m-%d")


def admin_token() -> str:
    return hmac.new(SECRET_KEY.encode(), ADMIN_PASSWORD.encode(), hashlib.sha256).hexdigest()


def require_admin() -> bool:
    return hmac.compare_digest(request.headers.get("X-Admin-Token", ""), admin_token())


def db(autocommit=True):
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=15)
    conn.autocommit = autocommit
    return conn


def init_db():
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS cg_sessions (
                code TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                account TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                biz_date TEXT NOT NULL,
                created_at BIGINT NOT NULL
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS cg_sessions_user_date_idx ON cg_sessions (user_id, biz_date)")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS cg_plays (
                id SERIAL PRIMARY KEY,
                code TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                account TEXT NOT NULL,
                biz_date TEXT NOT NULL,
                entry_no INTEGER NOT NULL,
                step INTEGER NOT NULL,
                prize INTEGER NOT NULL,
                played_at BIGINT NOT NULL,
                UNIQUE (user_id, biz_date, entry_no)
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS cg_plays_date_idx ON cg_plays (biz_date)")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS cg_settings (
                biz_date TEXT PRIMARY KEY,
                daily_cap INTEGER NOT NULL,
                updated_at BIGINT NOT NULL
            )
            """
        )


def clean_code(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())[:32] or "player"


def draw_step() -> int:
    r = secrets.randbelow(100)
    for i, w in enumerate(WEIGHTS):
        r -= w
        if r < 0:
            return i
    return 0


def find_user(cur, account: str):
    cur.execute(
        "SELECT user_id, account, COALESCE(real_name,'') AS real_name "
        "FROM users WHERE LOWER(account)=LOWER(%s) AND COALESCE(is_test,0)=0 LIMIT 1",
        (account.strip(),),
    )
    return cur.fetchone()


def window_deposits(cur, user_id: int, date: str):
    cur.execute(
        "SELECT amount, created_at FROM deposits "
        "WHERE user_id=%s AND biz_date=%s AND order_status='Success' "
        "AND substr(created_at,12,5) >= %s AND substr(created_at,12,5) < %s "
        "ORDER BY created_at",
        (user_id, date, DEP_FROM, DEP_TO),
    )
    return [{"amount": float(r["amount"]), "at": r["created_at"][11:16],
             "qualifies": float(r["amount"]) >= MIN_DEPOSIT} for r in cur.fetchall()]


def wagering(cur, user_id: int, date: str):
    """Valid bet in the allowed categories today. None if the category table isn't there."""
    try:
        cur.execute(
            "SELECT COALESCE(SUM(valid_bet),0) AS valid_bet, MAX(updated_at) AS synced_at "
            "FROM bets_daily_category WHERE user_id=%s AND biz_date=%s AND category = ANY(%s)",
            (user_id, date, WAGER_CATS),
        )
        r = cur.fetchone()
        return {"validBet": float(r["valid_bet"] or 0), "syncedAt": r["synced_at"]}
    except psycopg2.Error:
        return None


def plays_for(cur, user_id: int, date: str):
    cur.execute(
        "SELECT entry_no, step, prize, played_at FROM cg_plays "
        "WHERE user_id=%s AND biz_date=%s ORDER BY entry_no",
        (user_id, date),
    )
    return [dict(r) for r in cur.fetchall()]


def daily_cap_for(cur, date: str) -> int:
    cur.execute("SELECT daily_cap FROM cg_settings WHERE biz_date=%s", (date,))
    r = cur.fetchone()
    return int(r["daily_cap"]) if r else DAILY_CAP


def cap_used(cur, date: str) -> int:
    cur.execute("SELECT COALESCE(SUM(prize),0) AS used FROM cg_plays WHERE biz_date=%s", (date,))
    return int(cur.fetchone()["used"])


def cap_info(cur, date: str):
    cap = daily_cap_for(cur, date)
    used = cap_used(cur, date)
    left = max(0, cap - used)
    return {"dailyCap": cap, "capUsed": used, "capLeft": left, "capped": left < MIN_PRIZE}


def summary(cur, user, date: str):
    deps = window_deposits(cur, user["user_id"], date)
    qual = [d for d in deps if d["qualifies"]]
    plays = plays_for(cur, user["user_id"], date)
    used = len(plays)
    wag = wagering(cur, user["user_id"], date)
    valid = None if wag is None else wag["validBet"]
    # cumulative gate: entry i needs WAGER_MULT × (sum of qualifying deposits 1..i)
    entries, cum, unlocked = [], 0.0, 0
    for i, d in enumerate(qual, 1):
        cum += d["amount"]
        req = cum * WAGER_MULT
        ok = WAGER_MULT <= 0 or (valid is not None and valid >= req)
        if ok and unlocked == i - 1:
            unlocked = i
        entries.append({"no": i, "amount": d["amount"], "at": d["at"], "required": req,
                        "unlocked": ok, "played": i <= used})
    earned = len(qual)
    playable = max(0, unlocked - used)
    locked = max(0, earned - unlocked)
    next_req = entries[unlocked]["required"] if unlocked < earned else None
    t = now()
    hm = t.strftime("%H:%M")
    return {
        "account": user["account"],
        "name": user["real_name"] or user["account"],
        "date": date,
        "deposits": deps,
        "depositTotal": sum(d["amount"] for d in qual),
        "entries": entries,
        "entriesEarned": earned,
        "entriesUnlocked": unlocked,
        "entriesUsed": used,
        "entriesPlayable": playable,
        "entriesLocked": locked,
        "plays": plays,
        "wagering": None if wag is None else {
            "validBet": valid, "nextRequired": next_req, "syncedAt": wag["syncedAt"],
        },
        **cap_info(cur, date),
        "windowOpen": DEP_FROM <= hm < DEP_TO,
        "playOpen": hm <= PLAY_UNTIL,
        "serverTime": t.strftime("%Y-%m-%d %H:%M"),
    }


def post_ledger(payload: dict):
    def _go():
        try:
            req = urllib.request.Request(
                LEDGER_URL, data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            urllib.request.urlopen(req, timeout=8).read()
        except Exception:
            pass
    threading.Thread(target=_go, daemon=True).start()


# ---------------------------------------------------------------- admin API
@app.route("/api/admin-login", methods=["POST"])
def admin_login():
    payload = request.get_json(force=True, silent=True) or {}
    if not hmac.compare_digest(payload.get("password", ""), ADMIN_PASSWORD):
        return jsonify({"error": "invalid"}), 403
    return jsonify({"token": admin_token()})


@app.route("/api/lookup", methods=["GET"])
def lookup():
    if not require_admin():
        return jsonify({"error": "forbidden"}), 403
    account = (request.args.get("account") or "").strip()
    if not account:
        return jsonify({"error": "account required"}), 400
    date = today()
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        user = find_user(cur, account)
        if not user:
            return jsonify({"found": False, "account": account, **cap_info(cur, date)})
        s = summary(cur, user, date)
        cur.execute(
            "SELECT code FROM cg_sessions WHERE user_id=%s AND biz_date=%s ORDER BY created_at DESC LIMIT 1",
            (user["user_id"], date),
        )
        row = cur.fetchone()
    s["found"] = True
    s["code"] = row["code"] if row else None
    return jsonify(s)


@app.route("/api/link", methods=["POST"])
def make_link():
    """Create (or reuse) today's player link for an account. `fresh: true` forces a new code.
    Refused while today's budget is used up (admin can raise it with /api/cap)."""
    if not require_admin():
        return jsonify({"error": "forbidden"}), 403
    payload = request.get_json(force=True, silent=True) or {}
    account = (payload.get("account") or "").strip()
    fresh = bool(payload.get("fresh"))
    date = today()
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        user = find_user(cur, account)
        if not user:
            return jsonify({"error": "account not found"}), 404
        ci = cap_info(cur, date)
        if ci["capped"]:
            return jsonify({"error": "cap", "msg": "Naabot na ang daily budget — hindi makakagawa ng link. "
                            "Taasan ang budget kung kailangan.", **ci}), 409
        code = None
        if not fresh:
            cur.execute(
                "SELECT code FROM cg_sessions WHERE user_id=%s AND biz_date=%s ORDER BY created_at DESC LIMIT 1",
                (user["user_id"], date),
            )
            row = cur.fetchone()
            code = row["code"] if row else None
        if not code:
            code = clean_code(user["account"]) + "-" + secrets.token_hex(2)
            cur.execute(
                "INSERT INTO cg_sessions (code, user_id, account, name, biz_date, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (code, user["user_id"], user["account"], user["real_name"] or "", date, int(time.time() * 1000)),
            )
        s = summary(cur, user, date)
    s["found"] = True
    s["code"] = code
    return jsonify(s)


@app.route("/api/cap", methods=["GET", "POST"])
def cap():
    """GET: today's budget. POST {dailyCap}: set today's budget (>= what's already awarded)."""
    if not require_admin():
        return jsonify({"error": "forbidden"}), 403
    date = today()
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if request.method == "POST":
            payload = request.get_json(force=True, silent=True) or {}
            try:
                new_cap = int(payload.get("dailyCap"))
            except (TypeError, ValueError):
                return jsonify({"error": "dailyCap must be a whole number"}), 400
            used = cap_used(cur, date)
            if new_cap < used:
                return jsonify({"error": "below used", "msg": "Hindi pwedeng mas mababa sa nagamit na (₱%d)." % used}), 400
            if new_cap > 1_000_000:
                return jsonify({"error": "too high"}), 400
            cur.execute(
                "INSERT INTO cg_settings (biz_date, daily_cap, updated_at) VALUES (%s,%s,%s) "
                "ON CONFLICT (biz_date) DO UPDATE SET daily_cap=EXCLUDED.daily_cap, updated_at=EXCLUDED.updated_at",
                (date, new_cap, int(time.time() * 1000)),
            )
        return jsonify({"ok": True, "date": date, "defaultCap": DAILY_CAP, **cap_info(cur, date)})


# ---------------------------------------------------------------- player API
@app.route("/api/config", methods=["GET"])
def config():
    return jsonify(CONFIG)


def _pub(s):
    return {k: s[k] for k in ("entriesEarned", "entriesUnlocked", "entriesUsed", "entriesPlayable",
                              "entriesLocked", "plays", "wagering", "capLeft", "capped", "windowOpen",
                              "playOpen", "serverTime")}


@app.route("/api/session/<code>", methods=["GET"])
def get_session(code):
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM cg_sessions WHERE code=%s", (code,))
        sess = cur.fetchone()
        if not sess:
            return jsonify({"exists": False})
        date = today()
        user = {"user_id": sess["user_id"], "account": sess["account"], "real_name": sess["name"]}
        s = summary(cur, user, sess["biz_date"])
    expired = sess["biz_date"] != date
    out = {"exists": True, "code": code, "name": sess["name"] or sess["account"], "account": sess["account"],
           "expired": expired, "config": CONFIG, **_pub(s)}
    if expired:
        out.update({"entriesPlayable": 0, "entriesLocked": 0, "playOpen": False})
    return jsonify(out)


@app.route("/api/play/<code>", methods=["POST"])
def play(code):
    """Consume one unlocked entry: server draws the prize. Row-locked so double taps can't double-award."""
    conn = db(autocommit=False)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM cg_sessions WHERE code=%s FOR UPDATE", (code,))
        sess = cur.fetchone()
        if not sess:
            conn.rollback()
            return jsonify({"error": "no_session", "msg": "Hindi valid ang link."}), 404
        date = today()
        if sess["biz_date"] != date:
            conn.rollback()
            return jsonify({"error": "expired", "msg": "Expired na ang link na ito (ibang araw na)."}), 409
        if now().strftime("%H:%M") > PLAY_UNTIL:
            conn.rollback()
            return jsonify({"error": "closed", "msg": "Sarado na ang laro para ngayong araw."}), 409
        user = {"user_id": sess["user_id"], "account": sess["account"], "real_name": sess["name"]}
        # the session row lock serialises plays per link; UNIQUE(user_id,biz_date,entry_no)
        # catches a race between two links issued for the same account
        s = summary(cur, user, date)
        if s["entriesEarned"] == 0:
            conn.rollback()
            return jsonify({"error": "no_entries", "msg": "Wala ka pang entry. Isang deposit na ₱%d pataas (%s–%s) = 1 palo."
                            % (MIN_DEPOSIT, DEP_FROM, DEP_TO), **_pub(s)}), 409
        if s["entriesUsed"] >= s["entriesEarned"]:
            conn.rollback()
            return jsonify({"error": "no_entries", "msg": "Ubos na ang entries mo ngayon.", **_pub(s)}), 409
        if s["entriesPlayable"] <= 0:
            conn.rollback()
            w = s["wagering"] or {}
            return jsonify({"error": "locked", "msg": "Naka-lock pa ang susunod na palo: kailangan ng ₱%s turnover sa slots/casino "
                            "(meron ka pang ₱%s)." % (f"{(w.get('nextRequired') or 0):,.0f}", f"{(w.get('validBet') or 0):,.0f}"),
                            **_pub(s)}), 409
        step = draw_step()
        prize = PRIZES[step]
        if s["capUsed"] + prize > s["dailyCap"]:
            conn.rollback()
            return jsonify({"error": "cap", "msg": "Naabot na ang daily bonus budget. Subukan ulit bukas.", **_pub(s)}), 409
        entry_no = s["entriesUsed"] + 1
        cur.execute(
            "INSERT INTO cg_plays (code, user_id, account, biz_date, entry_no, step, prize, played_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (code, sess["user_id"], sess["account"], date, entry_no, step, prize, int(time.time() * 1000)),
        )
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback()
        return jsonify({"error": "race", "msg": "Subukan ulit."}), 409
    finally:
        conn.close()
    post_ledger({"brand": BRAND, "game": GAME_NAME, "name": sess["account"], "code": code,
                 "amount": prize, "link": request.headers.get("Referer", "")})
    return jsonify({"ok": True, "step": step, "prize": prize, "entryNo": entry_no,
                    "entriesPlayable": s["entriesPlayable"] - 1, "entriesLocked": s["entriesLocked"],
                    "entriesEarned": s["entriesEarned"], "entriesUsed": entry_no,
                    "capLeft": max(0, s["dailyCap"] - s["capUsed"] - prize)})


# ---------------------------------------------------------------- static
@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/health")
def health():
    return jsonify({"ok": True, "time": now().isoformat()})


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(STATIC_DIR, path)


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

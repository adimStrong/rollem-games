"""Gopyesta · Palarong Pyesta (Basag Palayok) — backend-verified community game.

Reads the Gopyesta platform Postgres (deposits / users / bets_daily_category, filled by the
gopyesta-retention pullers) to turn today's real deposits into game entries, draws every prize
SERVER-SIDE, enforces the daily bonus cap, and records every win in the shared wins-ledger.

Mechanics (whiteboard "GPT2027 — Community Game Mechanics", Gopyesta column):
  * every ₱100 of Success deposits made 1 PM–9 PM today = 1 entry (palo)
  * prizes ₱17 (85%) · ₱27 (10%) · ₱37 (5%) · ₱77 (display only, 0%)
  * only slots (egame) & casino bets count toward the 3× (of deposit) wagering requirement —
    reported to the agent, not enforced before play (bets sync every ~2 h)
  * max ₱10,000 bonus awarded per day across all players

Tables it OWNS in that database (created on boot, prefixed cg_): cg_sessions, cg_plays.
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
ENTRY_PESO = int(os.environ.get("ENTRY_PESO", "100"))
PRIZES = [int(x) for x in os.environ.get("PRIZES", "17,27,37,77").split(",")]
WEIGHTS = [int(x) for x in os.environ.get("WEIGHTS", "85,10,5,0").split(",")]
DAILY_CAP = int(os.environ.get("DAILY_CAP", "10000"))
WAGER_MULT = int(os.environ.get("WAGER_MULT", "3"))
WAGER_CATS = [c.strip() for c in os.environ.get("WAGER_CATS", "egame,casino").split(",") if c.strip()]
DEP_FROM = os.environ.get("DEP_FROM", "13:00")   # deposits counted from (inclusive, HH:MM)
DEP_TO = os.environ.get("DEP_TO", "21:00")       # deposits counted until (exclusive)
PLAY_UNTIL = os.environ.get("PLAY_UNTIL", "23:59")  # entries playable until this time, same day
assert len(PRIZES) == len(WEIGHTS) and sum(WEIGHTS) == 100

CONFIG = {
    "brand": BRAND, "game": GAME_NAME, "entryPeso": ENTRY_PESO, "prizes": PRIZES, "weights": WEIGHTS,
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
    return [{"amount": float(r["amount"]), "at": r["created_at"][11:16]} for r in cur.fetchall()]


def wagering(cur, user_id: int, date: str):
    """Valid bet in the allowed categories today. None if the category table isn't there yet."""
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


def cap_used(cur, date: str) -> int:
    cur.execute("SELECT COALESCE(SUM(prize),0) AS used FROM cg_plays WHERE biz_date=%s", (date,))
    return int(cur.fetchone()["used"])


def summary(cur, user, date: str):
    deps = window_deposits(cur, user["user_id"], date)
    dep_total = sum(d["amount"] for d in deps)
    earned = int(dep_total // ENTRY_PESO)
    plays = plays_for(cur, user["user_id"], date)
    used = len(plays)
    wag = wagering(cur, user["user_id"], date)
    required = dep_total * WAGER_MULT
    cap = cap_used(cur, date)
    t = now()
    hm = t.strftime("%H:%M")
    return {
        "account": user["account"],
        "name": user["real_name"] or user["account"],
        "date": date,
        "deposits": deps,
        "depositTotal": dep_total,
        "entriesEarned": earned,
        "entriesUsed": used,
        "entriesLeft": max(0, earned - used),
        "plays": plays,
        "wagering": None if wag is None else {
            "validBet": wag["validBet"], "required": required,
            "met": wag["validBet"] >= required and required > 0,
            "syncedAt": wag["syncedAt"],
        },
        "capUsed": cap,
        "capLeft": max(0, DAILY_CAP - cap),
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
            return jsonify({"found": False, "account": account, "capUsed": cap_used(cur, date),
                            "capLeft": max(0, DAILY_CAP - cap_used(cur, date))})
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
    """Create (or reuse) today's player link for an account. `fresh: true` forces a new code."""
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
    s["code"] = code
    return jsonify(s)


# ---------------------------------------------------------------- player API
@app.route("/api/config", methods=["GET"])
def config():
    return jsonify(CONFIG)


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
    return jsonify({
        "exists": True, "code": code, "name": sess["name"] or sess["account"], "account": sess["account"],
        "expired": expired, "entriesEarned": s["entriesEarned"], "entriesUsed": s["entriesUsed"],
        "entriesLeft": 0 if expired else s["entriesLeft"], "plays": s["plays"],
        "capLeft": s["capLeft"], "playOpen": s["playOpen"] and not expired,
        "windowOpen": s["windowOpen"], "serverTime": s["serverTime"], "config": CONFIG,
    })


@app.route("/api/play/<code>", methods=["POST"])
def play(code):
    """Consume one entry: server draws the prize. Row-locked so double taps can't double-award."""
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
        if s["entriesLeft"] <= 0:
            conn.rollback()
            return jsonify({"error": "no_entries", "msg": "Wala ka nang entry. Bawat ₱%d na deposit (%s–%s) = 1 palo."
                            % (ENTRY_PESO, DEP_FROM, DEP_TO), **_pub(s)}), 409
        step = draw_step()
        prize = PRIZES[step]
        if s["capUsed"] + prize > DAILY_CAP:
            conn.rollback()
            return jsonify({"error": "cap", "msg": "Naabot na ang daily bonus cap. Subukan ulit bukas.", **_pub(s)}), 409
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
                    "entriesLeft": s["entriesLeft"] - 1, "capLeft": max(0, DAILY_CAP - s["capUsed"] - prize)})


def _pub(s):
    return {"entriesEarned": s["entriesEarned"], "entriesUsed": s["entriesUsed"], "entriesLeft": s["entriesLeft"],
            "capLeft": s["capLeft"]}


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

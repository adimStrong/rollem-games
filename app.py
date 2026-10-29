"""Gopyesta · Lucky Ferris Wheel v2 — fixed prize ladder (replaces the deposit-tiered cabin design, 2026-10-25).

Reads the Gopyesta platform Postgres (deposits / users / bets_daily_category, filled by the
gopyesta-retention pullers), checks the player's REAL deposit + slot/casino turnover for the
day, rolls the reward SERVER-SIDE from a fixed prize ladder, enforces the daily bonus budget,
and records every win in the shared wins-ledger. Payout stays a manual GCash send tracked
there (Paid / Revoke).

Mechanics (from the "GoPyesta Lucky Ferris Wheel" raw export, Oct 23 2026, adopted in full
except the admin/turnover side — that stays on the platform's own database instead of the
export's manual-entry / claude.ai-artifact-db flow, which doesn't work self-hosted anyway):
  * fixed prize ladder for EVERY player, drawn server-side: ₱17 (85%) · ₱27 (10%) · ₱37 (5%)
    · ₱77 (display-only jackpot, 0% — shown in the odds table, never actually awarded)
  * eligible once today's Success deposits total >= MIN_DEPOSIT (₱200) made 12 PM-9 PM PH time
    AND today's slot+casino valid bet >= TURNOVER_MULT (1x) the deposit total
  * which of the 8 cabins the player taps is PURELY COSMETIC — it does not affect the odds or
    the amount, only which gondola visually reveals the already-drawn prize (kept so the
    session API shape — /api/pick then /api/spin — didn't need to change)
  * unlimited spins per day (2026-10-29: was 1/day) — depositing again and clearing the
    turnover gate again earns another spin; each spin's reward then needs a further
    TURNOVER_MULT x slot+casino turnover (tracked the same way as before) before it counts
    as "cleared" for payout; the real limiter on total spins/day is the daily bonus budget below
  * ₱10,000 bonus budget per day across all players (cg_settings per day, raisable by admin)

Tables it OWNS in that database (created on boot, unchanged from v1): cg_sessions, cg_settings,
fw_spins. `tier` is now always written as 0 (column kept, no DB migration needed) since there
is no longer a tier-to-cabin mapping.
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import urllib.request
from datetime import datetime, timedelta
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
GAME_NAME = "Lucky Ferris Wheel"
_DEFAULT_PRIZES = [[17, 85], [27, 10], [37, 5], [77, 0]]
PRIZES = [{"amt": int(a), "p": int(p)} for a, p in json.loads(os.environ.get("PRIZES") or json.dumps(_DEFAULT_PRIZES))]
LIVE_PRIZES = [p for p in PRIZES if p["p"] > 0]
assert LIVE_PRIZES, "PRIZES must include at least one prize with p > 0"
N = int(os.environ.get("WHEEL_CABINS", "8"))        # cosmetic only — which gondola reveals the prize
MIN_DEPOSIT = int(os.environ.get("MIN_DEPOSIT", "200"))         # deposits for the day must total at least this
TURNOVER_MULT = float(os.environ.get("TURNOVER_MULT", "1"))     # eligibility gate AND post-win clearing multiplier
WAGER_CATS = [c.strip() for c in os.environ.get("WAGER_CATS", "egame,casino").split(",") if c.strip()]
DAILY_CAP = int(os.environ.get("DAILY_CAP", "10000"))
ROUNDS_PER_DAY = int(os.environ.get("ROUNDS_PER_DAY", "1"))   # EMERGENCY REVERT 2026-10-29: incremental-need math hits 0 once a round's baseline catches up to dep_total even with NO new deposit, making every further round free -- reverted to 1 until a real fix ships. See rollem-games memory.
DEP_FROM = os.environ.get("DEP_FROM", "12:00")   # deposits counted from (inclusive, HH:MM)
DEP_TO = os.environ.get("DEP_TO", "21:00")       # deposits counted until (exclusive)
PLAY_UNTIL = os.environ.get("PLAY_UNTIL", "21:00")
MIN_PRIZE = min(p["amt"] for p in LIVE_PRIZES)
MAX_PRIZE = max(p["amt"] for p in PRIZES)

CONFIG = {
    "brand": BRAND, "game": GAME_NAME, "version": "fw2", "cabins": N, "prizes": PRIZES,
    "minDeposit": MIN_DEPOSIT, "turnover": TURNOVER_MULT, "wagerCats": WAGER_CATS, "dailyCap": DAILY_CAP,
    "roundsPerDay": ROUNDS_PER_DAY, "depFrom": DEP_FROM, "depTo": DEP_TO, "playUntil": PLAY_UNTIL, "maxPrize": MAX_PRIZE,
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
            CREATE TABLE IF NOT EXISTS cg_settings (
                biz_date TEXT PRIMARY KEY,
                daily_cap INTEGER NOT NULL,
                updated_at BIGINT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS fw_spins (
                id SERIAL PRIMARY KEY,
                code TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                account TEXT NOT NULL,
                biz_date TEXT NOT NULL,
                round_no INTEGER NOT NULL,
                cabin INTEGER NOT NULL,
                tier INTEGER NOT NULL,
                need INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                amount INTEGER NOT NULL DEFAULT 0,
                dep DOUBLE PRECISION NOT NULL DEFAULT 0,
                slot DOUBLE PRECISION NOT NULL DEFAULT 0,
                slot_base DOUBLE PRECISION NOT NULL DEFAULT 0,
                seen INTEGER NOT NULL DEFAULT 0,
                created_at BIGINT NOT NULL,
                spun_at BIGINT,
                cleared_at BIGINT,
                UNIQUE (user_id, biz_date, round_no)
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS fw_spins_date_idx ON fw_spins (biz_date, status)")
        cur.execute("CREATE INDEX IF NOT EXISTS fw_spins_user_idx ON fw_spins (user_id, status)")


def clean_code(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())[:32] or "player"


def ms():
    return int(time.time() * 1000)


def hm_of(t):
    return t.strftime("%H:%M")


def pick_prize() -> int:
    """Weighted random draw over the live (p > 0) prizes, matching the raw export's pickPrize()."""
    tot = sum(p["p"] for p in LIVE_PRIZES)
    r = secrets.randbelow(tot)
    for p in LIVE_PRIZES:
        r -= p["p"]
        if r < 0:
            return p["amt"]
    return LIVE_PRIZES[-1]["amt"]


def find_user(cur, account: str):
    """Look up by username, numeric user ID, or in-game ID ("GP"+referral_code) — same triple lookup as gopyesta-member-verify."""
    q = account.strip()
    rq = q[2:] if q.lower().startswith("gp") and len(q) > 2 else q  # in-game ID = "GP" + referral_code
    cur.execute(
        "SELECT user_id, account, COALESCE(real_name,'') AS real_name "
        "FROM users WHERE COALESCE(is_test,0)=0 AND (LOWER(account)=LOWER(%s) OR CAST(user_id AS TEXT)=%s "
        "OR LOWER(referral_code)=LOWER(%s)) LIMIT 1",
        (q, q, rq),
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


def bets_by_cat(cur, user_id: int, date: str):
    """{category: valid_bet} for the day + latest sync time. None if the table isn't there."""
    try:
        cur.execute(
            "SELECT category, COALESCE(valid_bet,0) AS valid_bet, updated_at FROM bets_daily_category "
            "WHERE user_id=%s AND biz_date=%s",
            (user_id, date),
        )
        rows = cur.fetchall()
    except psycopg2.Error:
        return None, None
    synced = max((r["updated_at"] or "" for r in rows), default=None) or None
    return {r["category"]: float(r["valid_bet"] or 0) for r in rows}, synced


def slot_bets_from(cur, user_id: int, date_from: str):
    """Valid bet in the counted categories on every day >= date_from (for turnover that spans days)."""
    try:
        cur.execute(
            "SELECT COALESCE(SUM(valid_bet),0) AS v FROM bets_daily_category "
            "WHERE user_id=%s AND biz_date >= %s AND category = ANY(%s)",
            (user_id, date_from, WAGER_CATS),
        )
        return float(cur.fetchone()["v"] or 0)
    except psycopg2.Error:
        return 0.0


def spins_for(cur, user_id: int, date: str):
    cur.execute("SELECT * FROM fw_spins WHERE user_id=%s AND biz_date=%s ORDER BY round_no", (user_id, date))
    return [dict(r) for r in cur.fetchall()]


def daily_cap_for(cur, date: str) -> int:
    cur.execute("SELECT daily_cap FROM cg_settings WHERE biz_date=%s", (date,))
    r = cur.fetchone()
    return int(r["daily_cap"]) if r else DAILY_CAP


def cap_used(cur, date: str) -> int:
    cur.execute("SELECT COALESCE(SUM(amount),0) AS used FROM fw_spins WHERE biz_date=%s AND status='paid'", (date,))
    return int(cur.fetchone()["used"])


def cap_info(cur, date: str):
    cap = daily_cap_for(cur, date)
    used = cap_used(cur, date)
    left = max(0, cap - used)
    return {"dailyCap": cap, "capUsed": used, "capLeft": left, "capped": left < MIN_PRIZE}


def pub_spin(r):
    return {"id": r["id"], "day": r["biz_date"], "round_no": r["round_no"], "cabin": r["cabin"],
            "need": int(r["need"]), "status": r["status"], "amount": int(r["amount"] or 0), "seen": int(r["seen"] or 0),
            "dep": float(r["dep"] or 0), "slot": float(r["slot"] or 0),
            "spun_at": datetime.fromtimestamp(r["spun_at"] / 1000, TZ).strftime("%Y-%m-%d %H:%M") if r.get("spun_at") else None,
            "cleared": bool(r.get("cleared_at"))}


def wager(cur, user_id: int):
    """Bonus awaiting turnover: TURNOVER_MULT × the uncleared rewards, in slot+casino bets made after the oldest one."""
    cur.execute("SELECT * FROM fw_spins WHERE user_id=%s AND status='paid' ORDER BY spun_at", (user_id,))
    rows = [dict(r) for r in cur.fetchall()]
    cleared = sum(int(r["amount"]) for r in rows if r.get("cleared_at"))
    open_rows = [r for r in rows if not r.get("cleared_at")]
    if not open_rows or TURNOVER_MULT <= 0:
        return {"bonus": 0, "need": 0, "done": 0, "cleared": cleared}
    bonus = sum(int(r["amount"]) for r in open_rows)
    need = bonus * TURNOVER_MULT
    first = open_rows[0]
    done = max(0.0, slot_bets_from(cur, user_id, first["biz_date"]) - float(first["slot_base"] or 0))
    if done >= need:
        cur.execute("UPDATE fw_spins SET cleared_at=%s WHERE id = ANY(%s)", (ms(), [r["id"] for r in open_rows]))
        return {"bonus": 0, "need": 0, "done": 0, "cleared": cleared + bonus}
    return {"bonus": bonus, "need": need, "done": done, "cleared": cleared}


def summary(cur, user, date: str):
    uid = user["user_id"]
    deps = window_deposits(cur, uid, date)
    dep_total = sum(d["amount"] for d in deps)
    cats, synced = bets_by_cat(cur, uid, date)
    slot_today = sum(v for c, v in (cats or {}).items() if c in WAGER_CATS)
    other = sum(v for c, v in (cats or {}).items() if c not in WAGER_CATS)
    rows = spins_for(cur, uid, date)
    cur_row = rows[-1] if rows else None
    # Baseline round that anchors the CURRENT/NEXT round's INCREMENTAL progress. While cur_row is
    # OPEN (in progress, not yet won), it hasn't consumed anything yet -- the baseline is the
    # round BEFORE it (rows[-2]). Once cur_row is PAID, it's the one most recently consumed, so
    # IT is the baseline for whatever comes next -- using rows[-2] there double-counted a paid
    # round's own consumption (broke starting at round 3, found 2026-10-29 adding unlimited
    # spins/day). `dep` (not `need`) is what reconstructs the baseline's absolute cumulative
    # target, since `need` itself is redefined below to be incremental, not cumulative.
    if cur_row is None:
        baseline = None
    elif cur_row["status"] == "open":
        baseline = rows[-2] if cur_row["round_no"] > 1 else None
    else:
        baseline = cur_row
    base = float(baseline["slot_base"] or 0) if baseline else 0.0
    prior_need = (max(MIN_DEPOSIT, float(baseline["dep"] or 0)) * TURNOVER_MULT) if baseline else 0.0
    slot = max(0.0, slot_today - base)
    t = now()
    hm = hm_of(t)
    dep_ok = dep_total >= MIN_DEPOSIT
    # THIS round's own incremental turnover target: the cumulative deposit-based target minus
    # whatever the baseline round already required -- NOT the full cumulative figure, which would
    # compare a RELATIVE `slot` against an ABSOLUTE target and demand far more than intended
    # (found 2026-10-29 via a real player: round 1 needed ₱200, round 2 was wrongly requiring
    # ₱625 absolute instead of ₱200 more on top of what round 1 already covered).
    need_amt = max(0.0, max(MIN_DEPOSIT, dep_total) * TURNOVER_MULT - prior_need)
    bet_ok = slot >= need_amt
    play_open = hm <= PLAY_UNTIL
    missing = []
    if not dep_ok:
        missing.append("mag-deposit pa ng ₱%s" % f"{MIN_DEPOSIT - dep_total:,.0f}")
    if not bet_ok:
        missing.append("mag-slots/casino pa ng ₱%s" % f"{need_amt - slot:,.0f}")
    wg = wager(cur, uid)   # may mark rows cleared -> fetch history after it
    cur.execute(
        "SELECT * FROM fw_spins WHERE user_id=%s AND status='paid' ORDER BY spun_at DESC LIMIT 30", (uid,))
    hist = [pub_spin(dict(r)) for r in cur.fetchall()]
    d0 = datetime.strptime(date, "%Y-%m-%d")
    mon = d0 - timedelta(days=d0.weekday())
    week_days = [(mon + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    paid_by_day = {}
    for h in hist:
        if h["day"] in week_days:
            paid_by_day[h["day"]] = paid_by_day.get(h["day"], 0) + h["amount"]
    week = [{"day": d, "amount": paid_by_day.get(d, None if (d == date and cur_row and cur_row["status"] == "open") else -1)}
            for d in week_days]
    return {
        "account": user["account"],
        "name": user["real_name"] or user["account"],
        "date": date,
        "deposits": deps,
        "dep": dep_total,
        "slot": slot,
        "slotToday": slot_today,
        "other": other,
        "syncedAt": synced,
        "cur": pub_spin(cur_row) if cur_row else None,
        "roundsUsed": len(rows),
        "canPick": (cur_row is not None and cur_row["status"] == "open") or len(rows) < ROUNDS_PER_DAY,
        "needAmt": need_amt,
        "depOk": dep_ok,
        "betOk": bet_ok,
        "ready": bool(cur_row) and cur_row["status"] == "open" and dep_ok and bet_ok and play_open,
        "missing": missing,
        "wager": wg,
        "hist": hist,
        "week": week,
        **cap_info(cur, date),
        "windowOpen": DEP_FROM <= hm < DEP_TO,
        "playOpen": play_open,
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
    """Create (or reuse) today's player link for an account. Auto-fresh: if the existing link's
    latest round has already been spun (paid), a new code is issued automatically -- the goal is
    tied to the account/day, not the code, so this is cosmetic, never resets progress. `fresh:
    true` still forces a new code outright (e.g. even while a round is still open).
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
            existing_code = row["code"] if row else None
            if existing_code:
                rows = spins_for(cur, user["user_id"], date)
                already_used = bool(rows) and rows[-1]["status"] == "paid"
                if not already_used:
                    code = existing_code
        if not code:
            code = clean_code(user["account"]) + "-" + secrets.token_hex(2)
            cur.execute(
                "INSERT INTO cg_sessions (code, user_id, account, name, biz_date, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (code, user["user_id"], user["account"], user["real_name"] or "", date, ms()),
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
                (date, new_cap, ms()),
            )
        return jsonify({"ok": True, "date": date, "defaultCap": DAILY_CAP, **cap_info(cur, date)})


# ---------------------------------------------------------------- player API
@app.route("/api/config", methods=["GET"])
def config():
    return jsonify(CONFIG)


_PUB = ("dep", "slot", "slotToday", "other", "syncedAt", "cur", "roundsUsed", "canPick", "needAmt", "depOk", "betOk",
        "ready", "missing", "wager", "hist", "week", "capLeft", "capped", "windowOpen", "playOpen", "serverTime")


def _pub(s):
    return {k: s[k] for k in _PUB}


def _session_state(cur, sess):
    date = today()
    user = {"user_id": sess["user_id"], "account": sess["account"], "real_name": sess["name"]}
    s = summary(cur, user, date)
    out = {"exists": True, "code": sess["code"], "name": sess["name"] or sess["account"], "account": sess["account"],
           "expired": sess["biz_date"] != date, "config": CONFIG, **_pub(s)}
    return out, s


@app.route("/api/session/<code>", methods=["GET"])
def get_session(code):
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM cg_sessions WHERE code=%s", (code,))
        sess = cur.fetchone()
        if not sess:
            return jsonify({"exists": False})
        out, _ = _session_state(cur, sess)
    return jsonify(out)


def _locked_session(cur, code):
    cur.execute("SELECT * FROM cg_sessions WHERE code=%s FOR UPDATE", (code,))
    return cur.fetchone()


@app.route("/api/pick/<code>", methods=["POST"])
def pick(code):
    """Pick cabin 1..N for today (purely cosmetic — doesn't change odds or the eligibility gate;
    kept so the player can still choose which gondola will reveal the prize)."""
    payload = request.get_json(force=True, silent=True) or {}
    try:
        cabin = int(payload.get("cabin"))
    except (TypeError, ValueError):
        cabin = 0
    if not 1 <= cabin <= N:
        return jsonify({"error": "bad_cabin", "msg": "Pumili ng cabin 1 hanggang %d." % N}), 400
    conn = db(autocommit=False)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        sess = _locked_session(cur, code)
        if not sess:
            conn.rollback()
            return jsonify({"error": "no_session", "msg": "Hindi valid ang link."}), 404
        date = today()
        if sess["biz_date"] != date:
            conn.rollback()
            return jsonify({"error": "expired", "msg": "Expired na ang link na ito (ibang araw na)."}), 409
        rows = spins_for(cur, sess["user_id"], date)
        cur_row = rows[-1] if rows else None
        user = {"user_id": sess["user_id"], "account": sess["account"], "real_name": sess["name"]}
        s = summary(cur, user, date)
        need_amt = int(round(s["needAmt"]))
        if cur_row and cur_row["status"] == "open":
            cur.execute("UPDATE fw_spins SET cabin=%s, tier=0, need=%s WHERE id=%s", (cabin, need_amt, cur_row["id"]))
        elif len(rows) >= ROUNDS_PER_DAY:
            conn.rollback()
            return jsonify({"error": "done", "msg": "Tapos na ang ikot mo ngayong araw. Pumili ulit bukas."}), 409
        else:
            cur.execute(
                "INSERT INTO fw_spins (code, user_id, account, biz_date, round_no, cabin, tier, need, status, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,0,%s,'open',%s)",
                (code, sess["user_id"], sess["account"], date, len(rows) + 1, cabin, need_amt, ms()),
            )
        out, _ = _session_state(cur, sess)
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback()
        return jsonify({"error": "race", "msg": "Subukan ulit."}), 409
    finally:
        conn.close()
    return jsonify(out)


@app.route("/api/spin/<code>", methods=["POST"])
def spin(code):
    """START: spin now if today's goal is met. Server draws from the fixed prize ladder; the
    session row lock serialises spins."""
    conn = db(autocommit=False)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        sess = _locked_session(cur, code)
        if not sess:
            conn.rollback()
            return jsonify({"error": "no_session", "msg": "Hindi valid ang link."}), 404
        date = today()
        if sess["biz_date"] != date:
            conn.rollback()
            return jsonify({"error": "expired", "msg": "Expired na ang link na ito (ibang araw na)."}), 409
        out, s = _session_state(cur, sess)
        c = s["cur"]
        if not c:
            conn.rollback()
            return jsonify({"error": "no_pick", "msg": "Pumili muna ng cabin.", **out}), 409
        if c["status"] == "paid":
            conn.rollback()
            return jsonify({"ok": True, "spun": False, "already": True, **out})
        if not s["playOpen"]:
            conn.rollback()
            return jsonify({"error": "closed", "msg": "Sarado na ang laro para ngayong araw.", **out}), 409
        if not s["ready"]:
            conn.rollback()
            return jsonify({"error": "locked", "msg": "Tapusin muna ang goal: " + " at ".join(s["missing"]) + ".", **out}), 409
        amount = pick_prize()
        if s["capUsed"] + amount > s["dailyCap"]:
            conn.rollback()
            return jsonify({"error": "cap", "msg": "Naabot na ang daily bonus budget. Subukan ulit bukas.", **out}), 409
        cur.execute(
            "UPDATE fw_spins SET status='paid', amount=%s, dep=%s, slot=%s, slot_base=%s, spun_at=%s, code=%s "
            "WHERE id=%s AND status='open'",
            (amount, s["dep"], s["slot"], s["slotToday"], ms(), code, c["id"]),
        )
        if cur.rowcount != 1:
            conn.rollback()
            return jsonify({"error": "race", "msg": "Subukan ulit."}), 409
        out, s = _session_state(cur, sess)
        conn.commit()
    finally:
        conn.close()
    post_ledger({"brand": BRAND, "game": GAME_NAME, "name": sess["account"], "code": code,
                 "amount": amount, "link": request.headers.get("Referer", "")})
    return jsonify({"ok": True, "spun": True, **out})


@app.route("/api/seen/<code>", methods=["POST"])
def seen(code):
    payload = request.get_json(force=True, silent=True) or {}
    try:
        sid = int(payload.get("id"))
    except (TypeError, ValueError):
        return jsonify({"error": "bad id"}), 400
    with db() as conn, conn.cursor() as cur:
        cur.execute("UPDATE fw_spins SET seen=1 WHERE id=%s AND code=%s", (sid, code))
    return jsonify({"ok": True})


# ---------------------------------------------------------------- static
@app.route("/")
def index():
    resp = send_from_directory(STATIC_DIR, "index.html", max_age=0)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


@app.route("/health")
def health():
    return jsonify({"ok": True, "game": GAME_NAME, "time": now().isoformat()})


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(STATIC_DIR, path)


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

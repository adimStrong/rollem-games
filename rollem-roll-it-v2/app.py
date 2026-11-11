"""Community game backend v3 — "plays" model (POTS Pearl Mine / TamasaPH Swerte Lights), backend-verified.

Same architecture as gopyesta-lucky-ferris-wheel-v2/app.py (2026-10-25), generalised:
  * the admin looks a player up in the brand's OWN platform database (filled by that brand's
    retention pullers), never types a deposit by hand — deposits and slot turnover are read live.
  * every PER_PLAY pesos of Success deposit in the DEP_FROM–DEP_TO window = 1 play (max MAX_PLAYS/day)
  * play k unlocks only once today's slot turnover >= TURNOVER_MULT × PER_PLAY × k (cumulative), so
    each play needs its own fresh 1× turnover — enforced server-side in /api/play, not just hinted.
  * the prize is drawn SERVER-SIDE (secrets) from a fixed ladder; the browser only animates the reveal
    (clams/pearls, light board) — a cosmetic "plan" it may store back for replay after a refresh.
  * daily bonus budget shared by all players (cg_settings per day), admin-raisable; global STOP ALL.
  * every win is POSTed to the shared wins-ledger (Risk pays out from its CSV export).

Platform data access lives in platform_<PLATFORM>.py (PLATFORM=pots -> Gobetplay-schema Postgres of
pots-retention; PLATFORM=tms -> tms-sync's tms_* tables). The game owns ONLY the cg_* tables below.
"""
import hashlib
import hmac
import importlib
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
REPORT_SHARE_TOKEN = os.environ.get("REPORT_SHARE_TOKEN", "")  # empty = public report mirror off
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
TZ = ZoneInfo(os.environ.get("TZ", "Asia/Manila"))

# ---- brand / game identity ----
PLATFORM = os.environ.get("PLATFORM", "pots")            # pots | tms
BRAND = os.environ.get("BRAND", "pots")                  # wins-ledger brand slug
BRAND_LABEL = os.environ.get("BRAND_LABEL", "POTS")
GAME_NAME = os.environ.get("GAME_NAME", "Pearl Mine")
platform = importlib.import_module("platform_" + PLATFORM)
WAGER_VERB = getattr(platform, "WAGER_VERB", "mag-slots")   # Taglish gate reason verb ("mag-slots pa ng ₱X" / "mag-bet pa ng ₱X")

# ---- mechanics (env-overridable, same knobs as the wheel) ----
PER_PLAY = float(os.environ.get("PER_PLAY", "150"))        # pesos of Success deposit per play
MAX_PLAYS = int(os.environ.get("MAX_PLAYS", "5"))          # plays per player per day (gopyesta precedent: 5)
TURNOVER_MULT = float(os.environ.get("TURNOVER_MULT", "1"))
WAGER_CATS = [c.strip() for c in os.environ.get("WAGER_CATS", "egame").split(",") if c.strip()]
DAILY_CAP = float(os.environ.get("DAILY_CAP", "10000"))
DEP_FROM = os.environ.get("DEP_FROM", "12:00")   # deposits counted from (inclusive, HH:MM)
DEP_TO = os.environ.get("DEP_TO", "21:00")       # deposits counted until (exclusive)
PLAY_FROM = os.environ.get("PLAY_FROM", DEP_FROM)
PLAY_UNTIL = os.environ.get("PLAY_UNTIL", "23:59")   # plays stay usable to end of day; the link still dies at midnight (biz_date)
# prize ladder: [[pesos, weight], ...]; weight 0 = display-only tier that is never drawn
_DEFAULT_PRIZES = "[[7,90],[17,10],[27,0],[57,0],[77,0],[777,0]]"  # 777 = display-only top rung (JD 2026-11-06, like the wheel)
PRIZES = [{"amt": float(a), "w": float(w)} for a, w in json.loads(os.environ.get("PRIZES") or _DEFAULT_PRIZES)]
LIVE_PRIZES = [p for p in PRIZES if p["w"] > 0]
assert LIVE_PRIZES, "PRIZES must include at least one prize with weight > 0"
# optional WILD round (Swerte Lights): WILD_RATE of plays draw from WILD_PRIZES instead (0 = off)
WILD_RATE = float(os.environ.get("WILD_RATE", "0"))
WILD_PRIZES = [{"amt": float(a), "w": float(w)} for a, w in json.loads(os.environ.get("WILD_PRIZES") or "[]")]
LIVE_WILD = [p for p in WILD_PRIZES if p["w"] > 0]
if WILD_RATE > 0:
    assert LIVE_WILD, "WILD_PRIZES must include a prize with weight > 0 when WILD_RATE > 0"
MIN_PRIZE = min(p["amt"] for p in (LIVE_PRIZES + LIVE_WILD))
MAX_PRIZE = max(p["amt"] for p in PRIZES + WILD_PRIZES)
_W_SCALE = 100  # weights are percents with up to 2 decimals -> exact integer draw


def _pct(ps):
    tot = sum(p["w"] for p in ps) or 1
    out = []
    for p in ps:
        v = round(p["w"] / tot * 100, 4)
        out.append({"amt": p["amt"], "p": int(v) if v == int(v) else v})
    return out


CONFIG = {
    "brand": BRAND, "brandLabel": BRAND_LABEL, "game": GAME_NAME, "platform": PLATFORM, "version": "cg3",
    "prizes": _pct(PRIZES), "wildRate": WILD_RATE, "wildPrizes": _pct(WILD_PRIZES),
    "perPlay": PER_PLAY, "maxPlays": MAX_PLAYS, "turnover": TURNOVER_MULT, "wagerCats": WAGER_CATS,
    "dailyCap": DAILY_CAP, "depFrom": DEP_FROM, "depTo": DEP_TO, "playFrom": PLAY_FROM, "playUntil": PLAY_UNTIL,
    "maxPrize": MAX_PRIZE, "minPrize": MIN_PRIZE,
}


# ---------------------------------------------------------------- helpers
def now():
    return datetime.now(TZ)


def today():
    return now().strftime("%Y-%m-%d")


def ms():
    return int(time.time() * 1000)


def hm_of(t):
    return t.strftime("%H:%M")


def pesos(c):
    """centavos -> number for JSON (int when whole)."""
    v = round(c / 100, 2)
    return int(v) if v == int(v) else v


def admin_token() -> str:
    return hmac.new(SECRET_KEY.encode(), ADMIN_PASSWORD.encode(), hashlib.sha256).hexdigest()


def require_admin() -> bool:
    return hmac.compare_digest(request.headers.get("X-Admin-Token", ""), admin_token())


def require_admin_or_share_token() -> bool:
    if require_admin():
        return True
    if not REPORT_SHARE_TOKEN:
        return False
    return hmac.compare_digest(request.args.get("token", ""), REPORT_SHARE_TOKEN)


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
                user_id BIGINT NOT NULL,
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
                daily_cap DOUBLE PRECISION NOT NULL,
                updated_at BIGINT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS cg_plays (
                id SERIAL PRIMARY KEY,
                code TEXT NOT NULL,
                user_id BIGINT NOT NULL,
                account TEXT NOT NULL,
                biz_date TEXT NOT NULL,
                play_no INTEGER NOT NULL,
                amount_c INTEGER NOT NULL,
                tier INTEGER NOT NULL DEFAULT 0,
                wild BOOLEAN NOT NULL DEFAULT FALSE,
                plan JSONB,
                status TEXT NOT NULL DEFAULT 'paid',
                need DOUBLE PRECISION NOT NULL DEFAULT 0,
                dep DOUBLE PRECISION NOT NULL DEFAULT 0,
                slot DOUBLE PRECISION NOT NULL DEFAULT 0,
                seen INTEGER NOT NULL DEFAULT 0,
                created_at BIGINT NOT NULL,
                cleared_at BIGINT,
                UNIQUE (user_id, biz_date, play_no)
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS cg_plays_date_idx ON cg_plays (biz_date, status)")
        cur.execute("CREATE INDEX IF NOT EXISTS cg_plays_user_idx ON cg_plays (user_id, status)")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS cg_kill_switch (
                id INTEGER PRIMARY KEY DEFAULT 1,
                stopped BOOLEAN NOT NULL DEFAULT FALSE,
                note TEXT NOT NULL DEFAULT '',
                updated_at BIGINT
            )
            """
        )
        cur.execute("INSERT INTO cg_kill_switch (id, stopped) VALUES (1, FALSE) ON CONFLICT (id) DO NOTHING")
        platform.ensure_schema(cur)


def clean_code(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())[:32] or "player"


def _draw(ps):
    weights = [int(round(p["w"] * _W_SCALE)) for p in ps]
    tot = sum(weights)
    r = secrets.randbelow(tot)
    for i, w in enumerate(weights):
        r -= w
        if r < 0:
            return i
    return len(ps) - 1


def pick_prize():
    """Server-side draw -> (amount_centavos, tier_index, wild). tier indexes PRIZES (or WILD_PRIZES when wild)."""
    if WILD_RATE > 0 and secrets.randbelow(1_000_000) < int(WILD_RATE * 1_000_000):
        i = _draw(LIVE_WILD)
        p = LIVE_WILD[i]
        return int(round(p["amt"] * 100)), WILD_PRIZES.index(p), True
    i = _draw(LIVE_PRIZES)
    p = LIVE_PRIZES[i]
    return int(round(p["amt"] * 100)), PRIZES.index(p), False


def plays_for(cur, user_id, date):
    cur.execute("SELECT * FROM cg_plays WHERE user_id=%s AND biz_date=%s ORDER BY play_no", (user_id, date))
    return [dict(r) for r in cur.fetchall()]


def links_issued_today(cur, user_id, date) -> int:
    cur.execute("SELECT COUNT(*) AS n FROM cg_sessions WHERE user_id=%s AND biz_date=%s", (user_id, date))
    return int(cur.fetchone()["n"])


def daily_cap_for(cur, date) -> float:
    cur.execute("SELECT daily_cap FROM cg_settings WHERE biz_date=%s", (date,))
    r = cur.fetchone()
    return float(r["daily_cap"]) if r else DAILY_CAP


def cap_used_c(cur, date) -> int:
    cur.execute("SELECT COALESCE(SUM(amount_c),0) AS used FROM cg_plays WHERE biz_date=%s AND status='paid'", (date,))
    return int(cur.fetchone()["used"])


def kill_switch_status(cur):
    cur.execute("SELECT stopped, note FROM cg_kill_switch WHERE id=1")
    r = cur.fetchone()
    return (bool(r["stopped"]), r["note"] or "") if r else (False, "")


def cap_info(cur, date):
    cap = daily_cap_for(cur, date)
    used = cap_used_c(cur, date) / 100
    left = max(0.0, cap - used)
    stopped, stop_note = kill_switch_status(cur)
    return {"dailyCap": cap, "capUsed": round(used, 2), "capLeft": round(left, 2), "capped": left < MIN_PRIZE,
            "stopped": stopped, "stopNote": stop_note}


def pub_play(r):
    return {"id": r["id"], "day": r["biz_date"], "play_no": r["play_no"], "amount": pesos(r["amount_c"]),
            "tier": int(r["tier"] or 0), "wild": bool(r.get("wild")), "plan": r.get("plan"),
            "status": r["status"], "seen": int(r["seen"] or 0), "need": float(r["need"] or 0),
            "dep": float(r["dep"] or 0), "slot": float(r["slot"] or 0),
            "at": datetime.fromtimestamp(r["created_at"] / 1000, TZ).strftime("%Y-%m-%d %H:%M") if r.get("created_at") else None,
            "cleared": bool(r.get("cleared_at"))}


def wager(cur, user_id):
    """Bonus awaiting clearing: TURNOVER_MULT x the uncleared rewards, in WAGER_CATS bets made after the oldest one (informational — Risk pays)."""
    cur.execute("SELECT * FROM cg_plays WHERE user_id=%s AND status='paid' ORDER BY created_at", (user_id,))
    rows = [dict(r) for r in cur.fetchall()]
    cleared = sum(r["amount_c"] for r in rows if r.get("cleared_at")) / 100
    open_rows = [r for r in rows if not r.get("cleared_at")]
    if not open_rows or TURNOVER_MULT <= 0:
        return {"bonus": 0, "need": 0, "done": 0, "cleared": cleared}
    bonus = sum(r["amount_c"] for r in open_rows) / 100
    need = bonus * TURNOVER_MULT
    first = open_rows[0]
    done = max(0.0, platform.slot_bets_from(cur, user_id, first["biz_date"], WAGER_CATS) - float(first["slot"] or 0))
    if done >= need:
        cur.execute("UPDATE cg_plays SET cleared_at=%s WHERE id = ANY(%s)", (ms(), [r["id"] for r in open_rows]))
        return {"bonus": 0, "need": 0, "done": 0, "cleared": cleared + bonus}
    return {"bonus": bonus, "need": need, "done": round(done, 2), "cleared": cleared}


def summary(cur, user, date):
    uid = user["user_id"]
    deps = platform.window_deposits(cur, uid, date, DEP_FROM, DEP_TO)
    dep_total = sum(d["amount"] for d in deps)
    slot_today, other, synced = platform.slot_turnover(cur, uid, date, WAGER_CATS)
    rows = plays_for(cur, uid, date)
    used = len(rows)
    plays_total = min(int(dep_total // PER_PLAY), MAX_PLAYS) if PER_PLAY > 0 else 0
    next_no = used + 1
    need = PER_PLAY * TURNOVER_MULT * next_no          # cumulative slot turnover needed for the NEXT play
    t = now()
    hm = hm_of(t)
    dep_ok = used < plays_total
    bet_ok = slot_today >= need
    play_open = PLAY_FROM <= hm <= PLAY_UNTIL
    missing = []
    if used >= MAX_PLAYS:
        missing.append("tapos na ang %d plays mo ngayong araw" % MAX_PLAYS)
    elif not dep_ok:
        missing.append("mag-deposit pa ng ₱%s" % f"{PER_PLAY * next_no - dep_total:,.0f}")
    if not bet_ok:
        missing.append("%s pa ng ₱%s" % (WAGER_VERB, f"{need - slot_today:,.0f}"))
    wg = wager(cur, uid)
    cur.execute("SELECT * FROM cg_plays WHERE user_id=%s AND status='paid' ORDER BY created_at DESC LIMIT 30", (uid,))
    hist = [pub_play(dict(r)) for r in cur.fetchall()]
    d0 = datetime.strptime(date, "%Y-%m-%d")
    mon = d0 - timedelta(days=d0.weekday())
    week_days = [(mon + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    paid_by_day = {}
    for h in hist:
        if h["day"] in week_days:
            paid_by_day[h["day"]] = round(paid_by_day.get(h["day"], 0) + h["amount"], 2)
    week = [{"day": d, "amount": paid_by_day.get(d, -1)} for d in week_days]
    ci = cap_info(cur, date)
    ready = dep_ok and bet_ok and play_open and not ci["stopped"] and not ci["capped"]
    return {
        "account": user["account"],
        "name": user["real_name"] or user["account"],
        "gameId": user.get("game_id") or "",
        "date": date,
        "deposits": deps,
        "dep": round(dep_total, 2),
        "slot": round(slot_today, 2),
        "other": round(other, 2),
        "syncedAt": synced,
        "plays": [pub_play(r) for r in rows],
        "playsUsed": used,
        "playsTotal": plays_total,
        "playsLeft": max(0, plays_total - used),
        "nextNeed": need,
        "linksIssued": links_issued_today(cur, uid, date),
        "depOk": dep_ok,
        "betOk": bet_ok,
        "ready": ready,
        "missing": missing,
        "wager": wg,
        "hist": hist,
        "week": week,
        **ci,
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
        user = platform.find_user(cur, account)
        if not user:
            return jsonify({"found": False, "account": account, **cap_info(cur, date)})
        s = summary(cur, user, date)
        cur.execute("SELECT code FROM cg_sessions WHERE user_id=%s AND biz_date=%s ORDER BY created_at DESC LIMIT 1",
                    (user["user_id"], date))
        row = cur.fetchone()
    s["found"] = True
    s["code"] = row["code"] if row else None
    return jsonify(s)


@app.route("/api/link", methods=["POST"])
def make_link():
    """Create (or reuse) today's player link. Progress is tied to the account+day, never the code."""
    if not require_admin():
        return jsonify({"error": "forbidden"}), 403
    payload = request.get_json(force=True, silent=True) or {}
    account = (payload.get("account") or "").strip()
    fresh = bool(payload.get("fresh"))
    date = today()
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        stopped, stop_note = kill_switch_status(cur)
        if stopped:
            return jsonify({"error": "stopped", "msg": "Hinarang ang laro ngayon" + (f" ({stop_note})" if stop_note else "") + " — hindi makakagawa ng bagong link."}), 409
        user = platform.find_user(cur, account)
        if not user:
            return jsonify({"error": "account not found"}), 404
        ci = cap_info(cur, date)
        if ci["capped"]:
            return jsonify({"error": "cap", "msg": "Naabot na ang daily budget — hindi makakagawa ng link. Taasan ang budget kung kailangan.", **ci}), 409
        code = None
        if not fresh:
            cur.execute("SELECT code FROM cg_sessions WHERE user_id=%s AND biz_date=%s ORDER BY created_at DESC LIMIT 1",
                        (user["user_id"], date))
            row = cur.fetchone()
            if row:
                code = row["code"]
        if not code:
            code = clean_code(user["account"]) + "-" + secrets.token_hex(2)
            cur.execute("INSERT INTO cg_sessions (code, user_id, account, name, biz_date, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
                        (code, user["user_id"], user["account"], user["real_name"] or "", date, ms()))
        s = summary(cur, user, date)
    s["found"] = True
    s["code"] = code
    return jsonify(s)


@app.route("/api/cap", methods=["GET", "POST"])
def cap():
    if not require_admin():
        return jsonify({"error": "forbidden"}), 403
    date = today()
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if request.method == "POST":
            payload = request.get_json(force=True, silent=True) or {}
            try:
                new_cap = float(payload.get("dailyCap"))
            except (TypeError, ValueError):
                return jsonify({"error": "dailyCap must be a number"}), 400
            used = cap_used_c(cur, date) / 100
            if new_cap < used:
                return jsonify({"error": "below used", "msg": "Hindi pwedeng mas mababa sa nagamit na (₱%.2f)." % used}), 400
            if new_cap > 1_000_000:
                return jsonify({"error": "too high"}), 400
            cur.execute("INSERT INTO cg_settings (biz_date, daily_cap, updated_at) VALUES (%s,%s,%s) "
                        "ON CONFLICT (biz_date) DO UPDATE SET daily_cap=EXCLUDED.daily_cap, updated_at=EXCLUDED.updated_at",
                        (date, new_cap, ms()))
        return jsonify({"ok": True, "date": date, "defaultCap": DAILY_CAP, **cap_info(cur, date)})


def _valid_iso_date(s):
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except (TypeError, ValueError):
        return False


@app.route("/api/links-today", methods=["GET"])
def links_today():
    """Every player with a link in [from,to] (PH dates, default today): links, plays, won, deposits, turnover."""
    if not require_admin_or_share_token():
        return jsonify({"error": "forbidden"}), 403
    t = today()
    date_from = request.args.get("from") or t
    date_to = request.args.get("to") or t
    if not _valid_iso_date(date_from):
        date_from = t
    if not _valid_iso_date(date_to):
        date_to = t
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT user_id, account, MAX(name) AS name, MAX(created_at) AS last_link_at, COUNT(*) AS links_issued "
                    "FROM cg_sessions WHERE biz_date BETWEEN %s AND %s GROUP BY user_id, account", (date_from, date_to))
        players = {r["user_id"]: dict(r) for r in cur.fetchall()}
        if players:
            cur.execute("SELECT user_id, COUNT(DISTINCT code) AS links, COUNT(*) AS rounds, "
                        "COALESCE(SUM(amount_c) FILTER (WHERE status='paid'),0) AS won "
                        "FROM cg_plays WHERE biz_date BETWEEN %s AND %s GROUP BY user_id", (date_from, date_to))
            for r in cur.fetchall():
                if r["user_id"] in players:
                    players[r["user_id"]].update(links=int(r["links"]), rounds=int(r["rounds"]), won=pesos(int(r["won"])))
            platform.enrich_players(cur, players, date_from, date_to, DEP_FROM, DEP_TO, WAGER_CATS)
    rows = list(players.values())
    for r in rows:
        r.setdefault("links", 0)
        r.setdefault("rounds", 0)
        r.setdefault("won", 0)
        r.setdefault("depAmount", 0)
        r.setdefault("depCount", 0)
        r.setdefault("turnover", 0)
        r.setdefault("gameId", "")
        r["links_issued"] = int(r.get("links_issued") or 0)
    rows.sort(key=lambda r: r["last_link_at"], reverse=True)
    return jsonify({"from": date_from, "to": date_to, "players": rows})


@app.route("/api/stop", methods=["GET", "POST"])
def stop_switch():
    if not require_admin():
        return jsonify({"error": "forbidden"}), 403
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if request.method == "POST":
            payload = request.get_json(force=True, silent=True) or {}
            stopped = bool(payload.get("stopped"))
            note = str(payload.get("note", ""))[:200]
            cur.execute("INSERT INTO cg_kill_switch (id, stopped, note, updated_at) VALUES (1,%s,%s,%s) "
                        "ON CONFLICT (id) DO UPDATE SET stopped=EXCLUDED.stopped, note=EXCLUDED.note, updated_at=EXCLUDED.updated_at",
                        (stopped, note, ms()))
        s, n = kill_switch_status(cur)
        return jsonify({"ok": True, "stopped": s, "stopNote": n})


# ---------------------------------------------------------------- player API
@app.route("/api/config", methods=["GET"])
def config():
    return jsonify(CONFIG)


_PUB = ("dep", "slot", "other", "syncedAt", "plays", "playsUsed", "playsTotal", "playsLeft", "nextNeed", "depOk", "betOk",
        "ready", "missing", "wager", "hist", "week", "capLeft", "capped", "windowOpen", "playOpen", "serverTime",
        "stopped", "stopNote")


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


@app.route("/api/play/<code>", methods=["POST"])
def play(code):
    """START: create + pay play N+1 if its deposit and cumulative turnover are in. Server draws the prize."""
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
        out, s = _session_state(cur, sess)
        if s["stopped"]:
            conn.rollback()
            return jsonify({"error": "stopped", "msg": "Hinarang ang laro ngayon" + (f" ({s['stopNote']})" if s["stopNote"] else "") + ".", **out}), 409
        if not s["playOpen"]:
            conn.rollback()
            return jsonify({"error": "closed", "msg": "Sarado na ang laro para ngayong araw.", **out}), 409
        if s["playsUsed"] >= MAX_PLAYS:
            conn.rollback()
            return jsonify({"error": "done", "msg": "Tapos na ang plays mo ngayong araw. Balik bukas.", **out}), 409
        if not s["depOk"]:
            # backend enforcement: a play needs its own new PER_PLAY deposit, not just the canPlay hint
            conn.rollback()
            return jsonify({"error": "no_new_deposit", "msg": "Walang bagong deposit pa. Mag-deposit muna para sa susunod na play.", **out}), 409
        if not s["betOk"]:
            conn.rollback()
            return jsonify({"error": "locked", "msg": "Tapusin muna ang goal: " + " at ".join(s["missing"]) + ".", **out}), 409
        amount_c, tier, wild = pick_prize()
        if s["capUsed"] + amount_c / 100 > s["dailyCap"]:
            conn.rollback()
            return jsonify({"error": "cap", "msg": "Naabot na ang daily bonus budget. Subukan ulit bukas.", **out}), 409
        play_no = s["playsUsed"] + 1
        cur.execute(
            "INSERT INTO cg_plays (code, user_id, account, biz_date, play_no, amount_c, tier, wild, status, need, dep, slot, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'paid',%s,%s,%s,%s) RETURNING *",
            (code, sess["user_id"], sess["account"], date, play_no, amount_c, tier, wild, s["nextNeed"], s["dep"], s["slot"], ms()),
        )
        row = dict(cur.fetchone())
        out, s = _session_state(cur, sess)
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback()
        return jsonify({"error": "race", "msg": "Subukan ulit."}), 409
    finally:
        conn.close()
    post_ledger({"brand": BRAND, "game": GAME_NAME, "name": sess["account"], "code": code,
                 "amount": pesos(amount_c), "link": request.headers.get("Referer", "")})
    return jsonify({"ok": True, "played": True, "play": pub_play(row), **out})


@app.route("/api/plan/<code>", methods=["POST"])
def save_plan(code):
    """Store the cosmetic reveal plan (which clams hold which pearl / where the light stops) so a refresh replays the SAME board. Never affects the amount."""
    payload = request.get_json(force=True, silent=True) or {}
    try:
        pid = int(payload.get("id"))
    except (TypeError, ValueError):
        return jsonify({"error": "bad id"}), 400
    plan = payload.get("plan")
    if not isinstance(plan, dict):
        return jsonify({"error": "bad plan"}), 400
    raw = json.dumps(plan, separators=(",", ":"))
    if len(raw) > 6000:
        return jsonify({"error": "plan too large"}), 400
    with db() as conn, conn.cursor() as cur:
        cur.execute("UPDATE cg_plays SET plan=%s::jsonb WHERE id=%s AND code=%s", (raw, pid, code))
        n = cur.rowcount
    return jsonify({"ok": n == 1})


@app.route("/api/seen/<code>", methods=["POST"])
def seen(code):
    payload = request.get_json(force=True, silent=True) or {}
    try:
        pid = int(payload.get("id"))
    except (TypeError, ValueError):
        return jsonify({"error": "bad id"}), 400
    with db() as conn, conn.cursor() as cur:
        cur.execute("UPDATE cg_plays SET seen=1 WHERE id=%s AND code=%s", (pid, code))
    return jsonify({"ok": True})


# ---------------------------------------------------------------- static
def _nostore(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


@app.route("/")
def index():
    return _nostore(send_from_directory(STATIC_DIR, "index.html", max_age=0))


@app.route("/health")
def health():
    return jsonify({"ok": True, "game": GAME_NAME, "brand": BRAND, "platform": PLATFORM, "time": now().isoformat()})


@app.route("/report")
def dev_report():
    return _nostore(send_from_directory(STATIC_DIR, "report.html", max_age=0))


@app.route("/report/<token>")
def dev_report_public(token):
    if not REPORT_SHARE_TOKEN or not hmac.compare_digest(token, REPORT_SHARE_TOKEN):
        return jsonify({"error": "not_found"}), 404
    return _nostore(send_from_directory(STATIC_DIR, "report-public.html", max_age=0))


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(STATIC_DIR, path)


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

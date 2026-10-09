"""Gopyesta · Lucky Ferris Wheel — backend-verified community game.

Replaces Palarong Pyesta (Palosebo) on this service. The backend it replaced was
sound, so the parts that carry money are kept exactly as they were: the per-player
link codes in `cg_sessions`, the admin link maker, the per-day budget in
`cg_settings`, the wins-ledger post, and `cg_plays` as the single award record.
What changed is the GAME on top of them.

Reads the Gopyesta platform Postgres (deposits / users / bets_daily_category, filled by the
gopyesta-retention pullers), gates the play behind the player's real turnover, draws the
bonus SERVER-SIDE, enforces the daily bonus budget, and records every win in the ledger.

Mechanics (from the Lucky Ferris Wheel design file):
  * the player locks ONE of 8 cabins for the day; cabins pair onto 4 tiers (1/5, 2/6, 3/7, 4/8)
  * each tier carries a turnover requirement and a HIDDEN bonus range:
        tier 1  ₱300 turnover -> ₱8–18      tier 3  ₱8,000  -> ₱18–188
        tier 2  ₱600 turnover -> ₱18–28     tier 4  ₱50,000 -> ₱288–888
  * to spin: a Success deposit of >= ₱100 today (inside the deposit window) AND valid bet in
    WAGER_CATS today >= the locked cabin's requirement
  * ONE release per player per PH day — held by UNIQUE (user_id, biz_date, entry_no) with
    entry_no pinned to 1, so the database enforces it rather than the code
  * the bonus is credited with a WAGER_MULT x turnover requirement before withdrawal
  * ₱10,000 bonus budget per day across all players; when reached, no NEW links and no new
    plays, but a player whose goal is already met is still paid — see play()
  * the requirement is shown to the player, the reward range never is: a range sent to the
    browser is a range in DevTools

Tables it OWNS in that database (created on boot, prefixed cg_): cg_sessions, cg_plays,
cg_settings, cg_ferris_picks.
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
GAME_NAME = "Lucky Ferris Wheel"
MIN_DEPOSIT = int(os.environ.get("MIN_DEPOSIT", os.environ.get("ENTRY_PESO", "100")))  # a deposit >= this qualifies the day
DAILY_CAP = int(os.environ.get("DAILY_CAP", "10000"))
# Bonus wagering: the win is credited with this multiple of turnover before it can be
# withdrawn. The design file says 5x; Lucky Spin moved the house standard to 8x on
# 2026-09-09, so this is env-overridable rather than a constant anyone has to go edit.
WAGER_MULT = float(os.environ.get("WAGER_MULT", "5"))
# Which bet categories count toward a cabin's requirement. The design file says "only slot
# bets count", which is 'egame' alone — but this service has been live on egame+casino, so
# that stays the default and the UI renders whatever is configured instead of claiming
# "slots" regardless. Set WAGER_CATS=egame to make the design file's wording literally true.
WAGER_CATS = [c.strip() for c in os.environ.get("WAGER_CATS", "egame,casino").split(",") if c.strip()]
DEP_FROM = os.environ.get("DEP_FROM", "13:00")   # deposits counted from (inclusive, HH:MM)
DEP_TO = os.environ.get("DEP_TO", "21:00")       # deposits counted until (exclusive)
PLAY_UNTIL = os.environ.get("PLAY_UNTIL", "23:59")  # playable until this time, same day

# cabin (1-based, as drawn) -> tier. Two cabins per tier, so the pick stays a guess even
# once a player has learnt what a tier costs.
CAB_TIER = [int(x) for x in os.environ.get("CAB_TIER", "1,2,3,4,1,2,3,4").split(",")]
N_CABINS = len(CAB_TIER)
# tier -> (turnover required today, bonus floor, bonus ceiling), in pesos.
TIERS = {
    1: tuple(int(x) for x in os.environ.get("TIER1", "300,8,18").split(",")),
    2: tuple(int(x) for x in os.environ.get("TIER2", "600,18,28").split(",")),
    3: tuple(int(x) for x in os.environ.get("TIER3", "8000,18,188").split(",")),
    4: tuple(int(x) for x in os.environ.get("TIER4", "50000,288,888").split(",")),
}
assert all(len(v) == 3 and v[1] <= v[2] for v in TIERS.values()), "TIERn = required,floor,ceiling"
assert set(CAB_TIER) <= set(TIERS), "CAB_TIER names a tier that does not exist"
MIN_PRIZE = min(v[1] for v in TIERS.values())
MAX_PRIZE = max(v[2] for v in TIERS.values())

CONFIG = {
    "brand": BRAND, "game": GAME_NAME, "minDeposit": MIN_DEPOSIT,
    "dailyCap": DAILY_CAP, "wagerMult": WAGER_MULT, "wagerCats": WAGER_CATS,
    "depFrom": DEP_FROM, "depTo": DEP_TO, "playUntil": PLAY_UNTIL,
    "cabins": N_CABINS, "cabTier": CAB_TIER,
    # Requirements only. The floors and ceilings are deliberately absent: the game hides
    # them behind "? ? ?" and this payload is readable by anyone holding a link.
    "tierRequired": {str(t): TIERS[t][0] for t in sorted(TIERS)},
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
        # `step` already holds the Palosebo placement index; for the ferris wheel it holds
        # the 0-based cabin, and `tier` is added beside it so a row can be read back without
        # having to know CAB_TIER at the time it was written.
        cur.execute("ALTER TABLE cg_plays ADD COLUMN IF NOT EXISTS tier INTEGER")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS cg_ferris_picks (
                user_id  INTEGER NOT NULL,
                biz_date TEXT NOT NULL,
                code     TEXT NOT NULL DEFAULT '',
                cabin    INTEGER NOT NULL,
                tier     INTEGER NOT NULL,
                created_at BIGINT NOT NULL,
                PRIMARY KEY (user_id, biz_date)
            )
            """
        )


def clean_code(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())[:32] or "player"


def tier_for_cabin(cabin) -> int:
    """Tier for a 1-based cabin, or 0 if the cabin is not on the wheel."""
    try:
        c = int(cabin)
    except (TypeError, ValueError):
        return 0
    return CAB_TIER[c - 1] if 1 <= c <= N_CABINS else 0


def draw_prize(tier: int) -> int:
    """A uniform peso amount inside the tier's range, drawn server-side.

    The design file rolled this in the browser, where a player could set the result from
    the console. `secrets` rather than `random` to match how this service already draws.
    """
    _req, lo, hi = TIERS.get(int(tier), (0, 0, 0))
    if hi <= 0:
        return 0
    return lo + secrets.randbelow(hi - lo + 1)


def pick_for(cur, user_id: int, date: str):
    cur.execute("SELECT cabin, tier FROM cg_ferris_picks WHERE user_id=%s AND biz_date=%s",
                (user_id, date))
    r = cur.fetchone()
    return {"cabin": int(r["cabin"]), "tier": int(r["tier"])} if r else None


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
        "SELECT entry_no, step, prize, tier, played_at FROM cg_plays "
        "WHERE user_id=%s AND biz_date=%s ORDER BY entry_no",
        (user_id, date),
    )
    return [dict(r) for r in cur.fetchall()]


def history_for(cur, user_id: int, days: int = 14):
    """Recent days for this player, newest first.

    Driven off the PICKS rather than the plays, so a day the player locked a cabin and never
    reached the goal comes back too — that is the design file's "not collected" state, and a
    week strip built only from wins would quietly hide it.
    """
    cur.execute(
        "SELECT p.biz_date, p.cabin, p.tier, pl.prize "
        "FROM cg_ferris_picks p "
        "LEFT JOIN cg_plays pl ON pl.user_id=p.user_id AND pl.biz_date=p.biz_date "
        "WHERE p.user_id=%s ORDER BY p.biz_date DESC LIMIT %s",
        (user_id, int(days)),
    )
    td = today()
    out = []
    for r in cur.fetchall():
        paid = r["prize"] is not None
        out.append({
            "date": r["biz_date"], "cabin": int(r["cabin"]), "tier": int(r["tier"]),
            "amount": int(r["prize"] or 0),
            "state": "paid" if paid else ("open" if r["biz_date"] == td else "missed"),
        })
    return out


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
    """The player's whole day, in one read.

    The `entries*` field names are kept from Palarong Pyesta on purpose. The ferris wheel is
    "one entry a day, unlocked by the locked cabin's turnover", which is the same shape the
    admin link maker already renders — so the admin contract survives the game change and
    only its wording had to move. The ferris-specific detail rides alongside.

    `wagering.validBet` is None when the category table cannot be read. That is treated as
    NOT met everywhere below: here turnover is the earning condition, so an unreadable
    figure must never resolve to "goal reached".
    """
    deps = window_deposits(cur, user["user_id"], date)
    qual = [d for d in deps if d["qualifies"]]
    plays = plays_for(cur, user["user_id"], date)
    wag = wagering(cur, user["user_id"], date)
    valid = None if wag is None else wag["validBet"]
    pick = pick_for(cur, user["user_id"], date)

    required = float(TIERS[pick["tier"]][0]) if pick else None
    deposit_total = sum(d["amount"] for d in qual)
    deposit_ok = len(qual) > 0
    turnover_ok = bool(pick) and valid is not None and valid >= required
    goal_met = deposit_ok and turnover_ok

    # One entry a day: earned once the deposit qualifies, unlocked once the cabin's
    # turnover is reached, used once it has paid.
    used = 1 if plays else 0
    earned = 1 if deposit_ok else 0
    unlocked = 1 if (earned and turnover_ok) else 0
    playable = max(0, unlocked - used)
    locked = max(0, earned - unlocked)
    win = plays[0] if plays else None

    t = now()
    hm = t.strftime("%H:%M")
    return {
        "account": user["account"],
        "name": user["real_name"] or user["account"],
        "date": date,
        "deposits": deps,
        "depositTotal": deposit_total,
        "depositOk": deposit_ok,
        "entries": [],
        "entriesEarned": earned,
        "entriesUnlocked": unlocked,
        "entriesUsed": used,
        "entriesPlayable": playable,
        "entriesLocked": locked,
        "plays": plays,
        # ferris detail
        "pick": pick,
        "required": required,
        "turnover": valid,
        "turnoverOk": turnover_ok,
        "goalMet": goal_met,
        "win": None if not win else {
            "cabin": int(win["step"]) + 1, "tier": win.get("tier"),
            "amount": int(win["prize"]), "wagerNeed": int(win["prize"]) * WAGER_MULT,
            "playedAt": win["played_at"],
        },
        "history": history_for(cur, user["user_id"]),
        "wagering": None if wag is None else {
            "validBet": valid, "nextRequired": required, "syncedAt": wag["syncedAt"],
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
                              "playOpen", "serverTime", "date",
                              "pick", "required", "turnover", "turnoverOk", "goalMet",
                              "depositTotal", "depositOk", "win", "history")}


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


@app.route("/api/ferris/pick/<code>", methods=["POST"])
def ferris_pick(code):
    """Lock today's cabin. First write wins; a later one is told what is already in force.

    The lock is the whole point: the requirement is visible and the reward is not, so a pick
    that could be changed after the goal was met would let a player clear the cheap cabin's
    turnover and then switch to the rich one.
    """
    payload = request.get_json(force=True, silent=True) or {}
    cabin = payload.get("cabin")
    tier = tier_for_cabin(cabin)
    if not tier:
        return jsonify({"error": "bad_cabin", "msg": "Pumili ng cabin 1 hanggang %d." % N_CABINS}), 400
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM cg_sessions WHERE code=%s", (code,))
        sess = cur.fetchone()
        if not sess:
            return jsonify({"error": "no_session", "msg": "Hindi valid ang link."}), 404
        date = today()
        if sess["biz_date"] != date:
            return jsonify({"error": "expired", "msg": "Expired na ang link na ito (ibang araw na)."}), 409
        cur.execute(
            "INSERT INTO cg_ferris_picks (user_id, biz_date, code, cabin, tier, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (user_id, biz_date) DO NOTHING",
            (sess["user_id"], date, code, int(cabin), tier, int(time.time() * 1000)),
        )
        held = pick_for(cur, sess["user_id"], date)
        user = {"user_id": sess["user_id"], "account": sess["account"], "real_name": sess["name"]}
        s = summary(cur, user, date)
    if not held:
        return jsonify({"error": "pick_failed", "msg": "Subukan ulit."}), 409
    return jsonify({"ok": True, "pick": held,
                    "lockedElsewhere": held["cabin"] != int(cabin), **_pub(s)})


@app.route("/api/play/<code>", methods=["POST"])
def play(code):
    """Spin the locked cabin: the server draws the bonus. Row-locked so double taps can't double-award."""
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
        # with entry_no pinned to 1 catches a race between two links for the same account
        s = summary(cur, user, date)
        if s["win"]:
            # A refresh lands here. It must show the amount already paid, never a new roll.
            conn.rollback()
            return jsonify({"ok": True, "replay": True, "cabin": s["win"]["cabin"],
                            "prize": s["win"]["amount"], "wagerNeed": s["win"]["wagerNeed"],
                            **_pub(s)})
        if not s["pick"]:
            conn.rollback()
            return jsonify({"error": "no_pick", "msg": "Pumili muna ng cabin.", **_pub(s)}), 409

        # The budget turns away a player who has NOT met the goal and pays one who has.
        # The goal is bought with turnover — up to ₱50,000 of it — and turnover is scoped to
        # the business day, so sending a met goal away "until tomorrow" would not defer the
        # reward, it would cancel it. Cost of honouring them: at most MAX_PRIZE each.
        if s["capped"] and not s["goalMet"]:
            conn.rollback()
            return jsonify({"error": "cap", "msg": "Naabot na ang daily bonus budget. "
                            "Huwag nang habulin ang goal ngayon — bukas ulit.", **_pub(s)}), 409
        if not s["depositOk"]:
            conn.rollback()
            return jsonify({"error": "no_entries", "msg": "Wala ka pang deposit ngayon. Isang deposit na ₱%d pataas (%s–%s)."
                            % (MIN_DEPOSIT, DEP_FROM, DEP_TO), **_pub(s)}), 409
        if not s["turnoverOk"]:
            conn.rollback()
            w = s["wagering"] or {}
            have = w.get("validBet")
            conn_msg = ("Hindi pa mabasa ang turnover mo — subukan ulit maya-maya."
                        if have is None else
                        "Naka-lock pa ang Cabin %d: kailangan ng ₱%s turnover (meron ka pang ₱%s)."
                        % (s["pick"]["cabin"], f"{(s['required'] or 0):,.0f}", f"{have:,.0f}"))
            return jsonify({"error": "locked", "msg": conn_msg, **_pub(s)}), 409

        cabin = s["pick"]["cabin"]
        tier = s["pick"]["tier"]
        prize = draw_prize(tier)
        cur.execute(
            "INSERT INTO cg_plays (code, user_id, account, biz_date, entry_no, step, prize, tier, played_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (code, sess["user_id"], sess["account"], date, 1, cabin - 1, prize, tier,
             int(time.time() * 1000)),
        )
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback()
        return jsonify({"error": "race", "msg": "Subukan ulit."}), 409
    finally:
        conn.close()
    post_ledger({"brand": BRAND, "game": GAME_NAME, "name": sess["account"], "code": code,
                 "amount": prize, "link": request.headers.get("Referer", "")})
    return jsonify({"ok": True, "cabin": cabin, "tier": tier, "prize": prize,
                    "wagerNeed": prize * WAGER_MULT, "entriesUsed": 1,
                    "entriesPlayable": 0, "entriesEarned": s["entriesEarned"],
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

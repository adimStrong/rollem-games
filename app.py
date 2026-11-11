"""GoBetplay "GoBet Race" — the first SHARED-EVENT game in this project.

Every other game here is one player per link: the player opens their own token URL and plays alone.
This one is a live carabao race with a roster. An agent adds qualified players to the open lobby, starts
the race, and everyone watching the same URL sees the same race, because the SERVER draws the outcome
and the browser only replays it. That contract is fixed by the dev's page, which polls `GET /api/race`
once a second and expects:

    { id, no, status: lobby|running|done, entries:[{userId,username}], maxEntries,
      startAt, serverNow, outcome, results, config }
    outcome = { seed, order[], times[], surge, crashes:[{idx,t}] }

`order[k]` is the racer index finishing in place k+1; `times` are finish seconds BY PLACE; `seed` drives
the page's cosmetic randomness through mulberry32 so every viewer sees an identical race.

House rule, taken from the dev source's own comments (index.html:220-223): the field is always 8 lanes,
empty lanes are filled with plausible-looking usernames, and **1st and 2nd always go to those fillers**.
A real player can only land 3rd (5%) or 4th and below. So of PRIZES = 177/77/27/7/7/7/7/7, a real player
can only ever win ₱27 or ₱7 — ₱177 and ₱77 are shown on the prize table and are unwinnable, the same
display-only pattern as ₱777 on every other brand. Expected cost per entry: .05*27 + .95*7 = ₱8.00.

Entry qualification matches the rest of the family (2026-11-11 window): a Success deposit of PER_ENTRY
made 12:00-21:00 PHT buys one entry, each entry needs TURNOVER_MULT x PER_ENTRY of turnover before it
can be used, MAX_ENTRIES_PER_DAY per player per day, DAILY_CAP shared across all players, and nothing
carries to tomorrow (every row is keyed by biz_date).

This app owns only its own gbr_* tables; `users`, `deposits` and `bets_daily_category` belong to the
GoBetplay platform database and are read-only here.
"""
import csv
import hashlib
import hmac
import io
import json
import os
import random
import threading
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

import importlib
import psycopg2
import psycopg2.extras
from flask import Flask, Response, jsonify, request, send_from_directory

app = Flask(__name__, static_folder=None)

DATABASE_URL = os.environ["DATABASE_URL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
SECRET_KEY = os.environ["SECRET_KEY"]
REPORT_SHARE_TOKEN = os.environ.get("REPORT_SHARE_TOKEN", "")
LEDGER_URL = os.environ.get("LEDGER_URL", "https://wins-ledger-production.up.railway.app/api/win")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
TZ = ZoneInfo(os.environ.get("TZ", "Asia/Manila"))

# ---- brand / game identity ----
PLATFORM = os.environ.get("PLATFORM", "gb")
BRAND = os.environ.get("BRAND", "gobetplay")              # wins-ledger brand slug
BRAND_LABEL = os.environ.get("BRAND_LABEL", "GoBetplay")
GAME_NAME = os.environ.get("GAME_NAME", "GoBet Race")
platform = importlib.import_module("platform_" + PLATFORM)

# ---- mechanics (same knobs as the other games) ----
PER_ENTRY = float(os.environ.get("PER_ENTRY", "200"))            # pesos of Success deposit per entry
MAX_ENTRIES_PER_DAY = int(os.environ.get("MAX_ENTRIES_PER_DAY", "5"))   # per player per day
TURNOVER_MULT = float(os.environ.get("TURNOVER_MULT", "1"))
WAGER_CATS = [c.strip() for c in os.environ.get("WAGER_CATS", "egame").split(",") if c.strip()]
DAILY_CAP = float(os.environ.get("DAILY_CAP", "10000"))
DEP_FROM = os.environ.get("DEP_FROM", "12:00")   # deposits counted from (inclusive, HH:MM)
DEP_TO = os.environ.get("DEP_TO", "21:00")       # deposits counted until (exclusive)
PLAY_FROM = os.environ.get("PLAY_FROM", DEP_FROM)
PLAY_UNTIL = os.environ.get("PLAY_UNTIL", "23:59")   # last minute a race may be STARTED

# ---- race shape (fixed by the dev page: 8 lanes, PRIZES by finishing place) ----
PRIZES = [float(x) for x in json.loads(os.environ.get("PRIZES") or "[177,77,27,7,7,7,7,7]")]
FIELD = int(os.environ.get("FIELD", "8"))
# THREE spare lanes, not two. 1st and 2nd always go to fillers, and 3rd only goes to a real player on
# the P3 roll -- so when that roll fails a third filler has to be available to take it. With only two
# spare lanes a full roster makes 3rd unfillable. This is why the dev page uses MAX_SLOTS=5 on a field
# of 8, and it is the number the admin panel's "(n/7)" text had wrong.
MAX_ENTRIES = min(int(os.environ.get("MAX_ENTRIES", str(FIELD - 3))), FIELD - 3)
P3 = float(os.environ.get("P3", "0.05"))                     # a real player's chance of 3rd
P4_GIVEN_NOT3 = float(os.environ.get("P4_GIVEN_NOT3", str(80.0 / 95.0)))
COUNTDOWN_MS = int(os.environ.get("COUNTDOWN_MS", "6000"))   # lobby -> flag drop
RACE_PAD_MS = int(os.environ.get("RACE_PAD_MS", "6000"))     # after the last finisher, before 'done'
FILLER_PREFIXES = [p.strip() for p in os.environ.get("FILLER_PREFIXES", "GBP,GBP,GBP,GB,GBX,PLY").split(",") if p.strip()]

MAX_PRIZE = max(PRIZES)
# A real player can only finish 3rd or worse, so these are the only amounts that can actually be paid.
LIVE_PRIZES = sorted(set(PRIZES[2:]))

CONFIG = {
    "brand": BRAND, "brandLabel": BRAND_LABEL, "game": GAME_NAME, "version": "gbr1",
    "perEntry": PER_ENTRY, "maxEntriesPerDay": MAX_ENTRIES_PER_DAY, "maxEntries": MAX_ENTRIES,
    "turnover": TURNOVER_MULT, "wagerCats": WAGER_CATS, "dailyCap": DAILY_CAP,
    "depFrom": DEP_FROM, "depTo": DEP_TO, "playFrom": PLAY_FROM, "playUntil": PLAY_UNTIL,
    "prizes": PRIZES, "field": FIELD, "maxPrize": MAX_PRIZE, "livePrizes": LIVE_PRIZES,
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


def peso(n):
    v = round(float(n), 2)
    return int(v) if v == int(v) else v


def peso_txt(n):
    v = peso(n)
    return "₱" + (("%d" % v) if isinstance(v, int) else ("%.2f" % v))


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


_SCHEMA_LOCK_ID = 714922301


def init_db():
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_ID,))
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS gbr_races (
                id BIGSERIAL PRIMARY KEY,
                no INTEGER NOT NULL,
                biz_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'lobby',   -- lobby | running | done
                outcome JSONB,
                results JSONB,
                start_at BIGINT,
                finish_at BIGINT,
                posted BOOLEAN NOT NULL DEFAULT FALSE,
                created_at BIGINT NOT NULL
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS gbr_races_date_idx ON gbr_races (biz_date, status)")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS gbr_entries (
                id BIGSERIAL PRIMARY KEY,
                race_id BIGINT NOT NULL REFERENCES gbr_races(id) ON DELETE CASCADE,
                idx INTEGER NOT NULL,
                user_id BIGINT,
                account TEXT NOT NULL,
                username TEXT NOT NULL DEFAULT '',
                house BOOLEAN NOT NULL DEFAULT FALSE,
                biz_date TEXT NOT NULL,
                place INTEGER,
                prize DOUBLE PRECISION,
                created_at BIGINT NOT NULL,
                UNIQUE (race_id, idx)
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS gbr_entries_user_date_idx ON gbr_entries (user_id, biz_date)")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS gbr_settings (
                biz_date TEXT PRIMARY KEY,
                daily_cap DOUBLE PRECISION NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS gbr_kill_switch (
                id INTEGER PRIMARY KEY,
                stopped BOOLEAN NOT NULL DEFAULT FALSE,
                note TEXT NOT NULL DEFAULT '',
                updated_at BIGINT
            )
            """
        )
        cur.execute("INSERT INTO gbr_kill_switch (id, stopped, note, updated_at) VALUES (1, FALSE, '', %s) "
                    "ON CONFLICT (id) DO NOTHING", (ms(),))
        platform.ensure_schema(cur)


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


# ---------------------------------------------------------------- the draw
def draw_outcome(n_real: int, n_total: int, rng: random.Random) -> dict:
    """Mirror of the placement rules in the dev page (index.html:894-917), but decided here so every
    viewer replays one identical race and so the odds cannot be inspected or nudged in the browser.

    Racer indices 0..n_real-1 are the real players (entry order); n_real..n_total-1 are the fillers.
    Returns the exact shape the page's newRace(spec) consumes.
    """
    # 1st, 2nd, and a 3rd that the P3 roll may decline all need a filler available.
    assert n_total - n_real >= 3, "need 3 spare lanes: %d real in a field of %d" % (n_real, n_total)
    filler = list(range(n_real, n_total))
    rng.shuffle(filler)
    place = [-1] * n_total          # place[k] = racer index that finishes in position k+1
    fi = 0

    # 1st and 2nd are always fillers: a real player can never win P177 or P77.
    place[0] = filler[fi]; fi += 1
    place[1] = filler[fi]; fi += 1

    ps = list(range(n_real))
    rng.shuffle(ps)
    # The page scales the 3rd-place chance by the number of players, so the per-player odds stay at P3.
    if ps and rng.random() < P3 * len(ps):
        place[2] = ps.pop(0)
    if ps and rng.random() < P4_GIVEN_NOT3:
        place[3] = ps.pop(0)
    rest = [q for q in range(4, n_total) if place[q] < 0]
    rng.shuffle(rest)
    if len(ps) > len(rest) and place[3] < 0:
        rest.insert(0, 3)
    for pi in ps:
        if not rest:
            break
        place[rest.pop(0)] = pi
    for q in range(n_total):
        if place[q] < 0:
            place[q] = filler[fi]; fi += 1
    order = place

    times = [15.0]
    for k in range(1, n_total):
        times.append(times[-1] + rng.uniform(0.06, 0.5) * (1.0 if k < 4 else 0.6))

    surge = order[1 + rng.randrange(max(1, min(2, n_total - 1)))]

    # Only fillers finishing behind EVERY real player may crash, so a crash can never move a player's place.
    last_real = max((q for q, ri in enumerate(order) if ri < n_real), default=1)
    pool = [ri for ri in order[last_real + 1:] if ri >= n_real and ri != surge]
    rng.shuffle(pool)
    n_crash = (1 if rng.random() < 0.5 else 2) if n_real >= 4 else (1 if n_real >= 2 else 0)
    slots = [rng.uniform(4.2, 6.2), rng.uniform(8.0, 9.6)]
    crashes = [{"idx": ri, "t": round(slots[k], 3)} for k, ri in enumerate(pool[:n_crash])]

    return {
        "seed": rng.randrange(1, 2 ** 31 - 1),
        "order": order,
        "times": [round(t, 3) for t in times],
        "surge": surge,
        "crashes": crashes,
    }


def filler_name(rng: random.Random, taken: set) -> str:
    """Plausible player handles for the empty lanes, in the same style the page used offline."""
    for _ in range(80):
        p = rng.choice(FILLER_PREFIXES)
        n = rng.randrange(0, 90000) + (100 if rng.random() < 0.5 else 10000)
        name = "%s%d" % (p, n)
        if name not in taken:
            taken.add(name)
            return name
    return "GBP%d" % (ms() % 100000)


# ---------------------------------------------------------------- day state
def kill_switch(cur):
    cur.execute("SELECT stopped, note FROM gbr_kill_switch WHERE id=1")
    r = cur.fetchone()
    return (bool(r["stopped"]), r["note"] or "") if r else (False, "")


def daily_cap_for(cur, date):
    cur.execute("SELECT daily_cap FROM gbr_settings WHERE biz_date=%s", (date,))
    r = cur.fetchone()
    return float(r["daily_cap"]) if r else DAILY_CAP


def cap_used(cur, date):
    cur.execute("SELECT COALESCE(SUM(prize),0) AS v FROM gbr_entries "
                "WHERE biz_date=%s AND house=FALSE AND prize IS NOT NULL", (date,))
    return float(cur.fetchone()["v"] or 0)


def entries_used_today(cur, user_id, date):
    cur.execute("SELECT COUNT(*) AS n FROM gbr_entries WHERE user_id=%s AND biz_date=%s AND house=FALSE",
                (user_id, date))
    return int(cur.fetchone()["n"] or 0)


def qualify(cur, user, date):
    """What this account is entitled to right now. Same shape of reasoning as the other games:
    deposits inside the window buy entries, each entry needs its own turnover, capped per day."""
    deps = platform.window_deposits(cur, user["user_id"], date, DEP_FROM, DEP_TO)
    dep_total = sum(d["amount"] for d in deps)
    entries_total = min(int(dep_total // PER_ENTRY), MAX_ENTRIES_PER_DAY)
    used = entries_used_today(cur, user["user_id"], date)
    slot, other, synced = platform.slot_turnover(cur, user["user_id"], date, WAGER_CATS)
    next_no = used + 1
    need = TURNOVER_MULT * PER_ENTRY * next_no
    missing = []
    if used >= entries_total:
        short = PER_ENTRY * next_no - dep_total
        if entries_total >= MAX_ENTRIES_PER_DAY:
            missing.append("abot na ang %d entries ngayong araw" % MAX_ENTRIES_PER_DAY)
        else:
            missing.append("mag-deposit pa ng %s" % peso_txt(max(0, short)))
    if slot < need:
        missing.append("mag-bet pa ng %s" % peso_txt(max(0, need - slot)))
    return {
        "userId": user["user_id"], "account": user["account"], "name": user.get("real_name", ""),
        "gameId": user.get("game_id", ""), "deposits": deps, "dep": peso(dep_total),
        "entriesTotal": entries_total, "entriesUsed": used, "entriesLeft": max(0, entries_total - used),
        "slot": peso(slot), "other": peso(other), "syncedAt": synced,
        "nextNeed": peso(need), "betOk": slot >= need, "depOk": used < entries_total,
        "ready": used < entries_total and slot >= need, "missing": missing,
    }


# ---------------------------------------------------------------- race state
def current_race(cur, date, create=True):
    cur.execute("SELECT * FROM gbr_races WHERE biz_date=%s ORDER BY no DESC LIMIT 1", (date,))
    r = cur.fetchone()
    if r:
        return dict(r)
    if not create:
        return None
    cur.execute("SELECT COALESCE(MAX(no),0) AS n FROM gbr_races WHERE biz_date=%s", (date,))
    no = int(cur.fetchone()["n"] or 0) + 1
    cur.execute("INSERT INTO gbr_races (no, biz_date, status, created_at) VALUES (%s,%s,'lobby',%s) RETURNING *",
                (no, date, ms()))
    return dict(cur.fetchone())


def race_entries(cur, race_id):
    cur.execute("SELECT * FROM gbr_entries WHERE race_id=%s ORDER BY idx", (race_id,))
    return [dict(r) for r in cur.fetchall()]


def finalize_if_due(conn, cur, race):
    """Lazy finalisation: the result was decided at start, so 'done' is purely a function of the clock.
    No scheduler needed -- whichever poll arrives first after finish_at records the wins (once)."""
    if race["status"] != "running" or not race["finish_at"] or ms() < race["finish_at"]:
        return race
    cur.execute("SELECT * FROM gbr_races WHERE id=%s FOR UPDATE", (race["id"],))
    fresh = dict(cur.fetchone())
    if fresh["status"] != "running" or fresh["posted"]:
        return fresh
    cur.execute("UPDATE gbr_races SET status='done', posted=TRUE WHERE id=%s RETURNING *", (race["id"],))
    out = dict(cur.fetchone())
    for e in race_entries(cur, race["id"]):
        if e["house"] or not e["prize"]:
            continue
        post_ledger({
            "brand": BRAND, "game": GAME_NAME, "name": e["account"], "code": e["account"],
            "amount": peso(e["prize"]),
            "link": "race-%d-%s-place-%s" % (out["no"], out["biz_date"], e["place"]),
        })
    conn.commit()
    return out


def pub_race(cur, race, include_outcome=True):
    entries = race_entries(cur, race["id"])
    out = {
        "id": "r%d" % race["id"],
        "no": race["no"],
        "status": race["status"],
        "bizDate": race["biz_date"],
        "entries": [{"userId": e["account"], "username": e["username"], "house": e["house"]} for e in entries],
        "maxEntries": MAX_ENTRIES,
        "field": FIELD,
        "startAt": race["start_at"],
        "serverNow": ms(),
        "outcome": race["outcome"] if (include_outcome and race["status"] != "lobby") else None,
        "config": CONFIG,
    }
    if race["status"] == "done" and race["results"]:
        out["results"] = race["results"]
    return out


# ---------------------------------------------------------------- public API
@app.route("/api/race", methods=["GET"])
def get_race():
    """Polled once a second by every open page. Must stay cheap and must never need auth."""
    conn = db(autocommit=False)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        date = today()
        race = current_race(cur, date)
        conn.commit()
        race = finalize_if_due(conn, cur, race)
        out = pub_race(cur, race)
        conn.commit()
        return jsonify(out)
    finally:
        conn.close()


@app.route("/api/config", methods=["GET"])
def get_config():
    t = now()
    hm = hm_of(t)
    return jsonify({**CONFIG, "serverTime": t.strftime("%Y-%m-%d %H:%M"),
                    "windowOpen": DEP_FROM <= hm < DEP_TO, "playOpen": PLAY_FROM <= hm <= PLAY_UNTIL})


# ---------------------------------------------------------------- admin API
@app.route("/api/admin-login", methods=["POST"])
def admin_login():
    payload = request.get_json(force=True, silent=True) or {}
    if not hmac.compare_digest(payload.get("password", ""), ADMIN_PASSWORD):
        return jsonify({"error": "invalid"}), 403
    return jsonify({"token": admin_token()})


@app.route("/api/admin/lookup", methods=["GET"])
def admin_lookup():
    if not require_admin():
        return jsonify({"error": "forbidden"}), 403
    account = (request.args.get("userId") or request.args.get("account") or "").strip()
    if not account:
        return jsonify({"error": "no_account"}), 400
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        date = today()
        user = platform.find_user(cur, account)
        if not user:
            return jsonify({"found": False, "account": account})
        q = qualify(cur, user, date)
        return jsonify({"found": True, **q, "capLeft": peso(max(0, daily_cap_for(cur, date) - cap_used(cur, date)))})


@app.route("/api/admin/entry", methods=["POST"])
def add_entry():
    if not require_admin():
        return jsonify({"error": "forbidden"}), 403
    payload = request.get_json(force=True, silent=True) or {}
    account = str(payload.get("userId", "")).strip()
    username = str(payload.get("username", "")).strip()[:40]
    if not account:
        return jsonify({"error": "no_account", "msg": "Type the player's User ID."}), 400

    conn = db(autocommit=False)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        date = today()
        hm = hm_of(now())
        stopped, note = kill_switch(cur)
        if stopped:
            return jsonify({"error": "stopped", "msg": "Hinarang ang laro ngayon" + ((" (%s)" % note) if note else "") + "."}), 409
        # entries only count inside the deposit window, same rule as every other brand
        if not (DEP_FROM <= hm < DEP_TO):
            return jsonify({"error": "closed",
                            "msg": "Sarado ang entry ngayon. Bukas ang entries %s-%s." % (DEP_FROM, DEP_TO)}), 409

        race = current_race(cur, date)
        if race["status"] != "lobby":
            return jsonify({"error": "not_lobby", "msg": "Tapos na ang lobby. Press 'New race' muna."}), 409
        entries = [e for e in race_entries(cur, race["id"]) if not e["house"]]
        if len(entries) >= MAX_ENTRIES:
            return jsonify({"error": "full", "msg": "Puno na ang race (%d players)." % MAX_ENTRIES}), 409

        user = platform.find_user(cur, account)
        if not user:
            return jsonify({"error": "not_found", "msg": "Hindi nakita ang account na '%s'." % account}), 404
        if any(e["user_id"] == user["user_id"] for e in entries):
            return jsonify({"error": "dup", "msg": "Nasa race na si %s." % user["account"]}), 409

        q = qualify(cur, user, date)
        if not q["ready"]:
            return jsonify({"error": "locked", "msg": "Hindi pa qualified: " + " at ".join(q["missing"]) + ".",
                            "lookup": q}), 409
        # Refuse rather than over-commit: the worst a real player can win is the 3rd-place prize.
        cap_left = daily_cap_for(cur, date) - cap_used(cur, date)
        if cap_left < PRIZES[2]:
            return jsonify({"error": "cap", "msg": "Naabot na ang daily bonus budget. Bukas na ulit."}), 409

        cur.execute(
            "INSERT INTO gbr_entries (race_id, idx, user_id, account, username, house, biz_date, created_at) "
            "VALUES (%s,%s,%s,%s,%s,FALSE,%s,%s)",
            (race["id"], len(entries), user["user_id"], user["account"], username or user.get("real_name", ""),
             date, ms()),
        )
        conn.commit()
        return jsonify(pub_race(cur, current_race(cur, date)))
    finally:
        conn.close()


@app.route("/api/admin/entry/<int:idx>", methods=["DELETE"])
def del_entry(idx):
    if not require_admin():
        return jsonify({"error": "forbidden"}), 403
    conn = db(autocommit=False)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        date = today()
        race = current_race(cur, date)
        if race["status"] != "lobby":
            return jsonify({"error": "not_lobby", "msg": "Nagsimula na ang race."}), 409
        cur.execute("DELETE FROM gbr_entries WHERE race_id=%s AND idx=%s AND house=FALSE", (race["id"], idx))
        # keep idx contiguous so the lane numbers the players see stay 1..n
        rows = race_entries(cur, race["id"])
        for new_idx, e in enumerate(rows):
            if e["idx"] != new_idx:
                cur.execute("UPDATE gbr_entries SET idx=%s WHERE id=%s", (new_idx, e["id"]))
        conn.commit()
        return jsonify(pub_race(cur, current_race(cur, date)))
    finally:
        conn.close()


@app.route("/api/admin/start", methods=["POST"])
def start_race():
    if not require_admin():
        return jsonify({"error": "forbidden"}), 403
    conn = db(autocommit=False)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        date = today()
        hm = hm_of(now())
        stopped, note = kill_switch(cur)
        if stopped:
            return jsonify({"error": "stopped", "msg": "Hinarang ang laro ngayon."}), 409
        if not (PLAY_FROM <= hm <= PLAY_UNTIL):
            return jsonify({"error": "closed",
                            "msg": "Sarado na ang laro para ngayong araw (%s-%s)." % (PLAY_FROM, PLAY_UNTIL)}), 409

        race = current_race(cur, date)
        cur.execute("SELECT * FROM gbr_races WHERE id=%s FOR UPDATE", (race["id"],))
        race = dict(cur.fetchone())
        if race["status"] != "lobby":
            return jsonify({"error": "not_lobby", "msg": "Nagsimula na ang race na ito."}), 409
        real = [e for e in race_entries(cur, race["id"]) if not e["house"]]
        if len(real) < 2:
            return jsonify({"error": "too_few", "msg": "Kailangan ng at least 2 players."}), 409

        rng = random.SystemRandom()
        # fill the empty lanes so the field is always full and 1st/2nd have someone to go to
        taken = {e["account"] for e in real}
        for k in range(len(real), FIELD):
            cur.execute(
                "INSERT INTO gbr_entries (race_id, idx, user_id, account, username, house, biz_date, created_at) "
                "VALUES (%s,%s,NULL,%s,'',TRUE,%s,%s)",
                (race["id"], k, filler_name(rng, taken), date, ms()),
            )
        entries = race_entries(cur, race["id"])
        n_real, n_total = len(real), len(entries)
        outcome = draw_outcome(n_real, n_total, rng)

        # the real players' prizes, and the cap check, before anything is committed
        results, total = [], 0.0
        for place0, ri in enumerate(outcome["order"]):
            e = entries[ri]
            prize = PRIZES[place0] if place0 < len(PRIZES) else 0.0
            house = e["house"]
            if not house:
                total += prize
            results.append({"place": place0 + 1, "carabao": ri + 1, "house": house,
                            "userId": e["account"], "prize": peso_txt(prize)})
        cap_left = daily_cap_for(cur, date) - cap_used(cur, date)
        if total > cap_left:
            conn.rollback()
            return jsonify({"error": "cap",
                            "msg": "Kulang ang natitirang budget (%s) para sa race na ito (%s)."
                                   % (peso_txt(cap_left), peso_txt(total))}), 409

        for place0, ri in enumerate(outcome["order"]):
            e = entries[ri]
            if not e["house"]:
                cur.execute("UPDATE gbr_entries SET place=%s, prize=%s WHERE id=%s",
                            (place0 + 1, PRIZES[place0] if place0 < len(PRIZES) else 0.0, e["id"]))
        start_at = ms() + COUNTDOWN_MS
        finish_at = start_at + int(max(outcome["times"]) * 1000) + RACE_PAD_MS
        cur.execute("UPDATE gbr_races SET status='running', outcome=%s, results=%s, start_at=%s, finish_at=%s "
                    "WHERE id=%s RETURNING *",
                    (json.dumps(outcome), json.dumps(results), start_at, finish_at, race["id"]))
        race = dict(cur.fetchone())
        conn.commit()
        return jsonify(pub_race(cur, race))
    finally:
        conn.close()


@app.route("/api/admin/new", methods=["POST"])
def new_race():
    if not require_admin():
        return jsonify({"error": "forbidden"}), 403
    conn = db(autocommit=False)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        date = today()
        race = current_race(cur, date)
        race = finalize_if_due(conn, cur, race)
        if race["status"] == "running":
            return jsonify({"error": "running", "msg": "Tumatakbo pa ang race."}), 409
        if race["status"] == "lobby":
            # already an open lobby; nothing to do
            return jsonify(pub_race(cur, race))
        cur.execute("INSERT INTO gbr_races (no, biz_date, status, created_at) VALUES (%s,%s,'lobby',%s) RETURNING *",
                    (race["no"] + 1, date, ms()))
        fresh = dict(cur.fetchone())
        conn.commit()
        return jsonify(pub_race(cur, fresh))
    finally:
        conn.close()


@app.route("/api/admin/history", methods=["GET"])
def history():
    if not require_admin():
        return jsonify({"error": "forbidden"}), 403
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        date = today()
        race = current_race(cur, date)
        cur.execute("SELECT id, no, biz_date, status, results FROM gbr_races "
                    "WHERE status='done' ORDER BY id DESC LIMIT 15")
        races = []
        for r in cur.fetchall():
            ents = race_entries(cur, r["id"])
            races.append({"no": r["no"], "bizDate": r["biz_date"], "results": r["results"] or [],
                          "entries": [{"userId": e["account"]} for e in ents if not e["house"]]})
        out = pub_race(cur, race)
        out["races"] = races
        out["capLeft"] = peso(max(0, daily_cap_for(cur, date) - cap_used(cur, date)))
        out["capUsed"] = peso(cap_used(cur, date))
        out["dailyCap"] = peso(daily_cap_for(cur, date))
        return jsonify(out)


@app.route("/api/admin/history.csv", methods=["GET"])
def history_csv():
    """The admin panel's "Download results (CSV)" is a plain <a href>, so it cannot send a header --
    it passes the same admin token as ?token=. Compared with compare_digest, not ==."""
    tok = request.args.get("token", "")
    if not hmac.compare_digest(tok, admin_token()):
        return "forbidden", 403
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT r.biz_date, r.no, e.place, e.account, e.username, e.prize, e.house "
            "FROM gbr_entries e JOIN gbr_races r ON r.id=e.race_id "
            "WHERE r.status='done' ORDER BY r.biz_date DESC, r.no DESC, e.place",
            (),
        )
        rows = cur.fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date_ph", "race", "place", "user_id", "username", "prize", "kind"])
    for r in rows:
        w.writerow([r["biz_date"], r["no"], r["place"] or "", r["account"], r["username"] or "",
                    peso(r["prize"] or 0), "filler" if r["house"] else "player"])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=gobet-race-results.csv"})


@app.route("/api/admin/cap", methods=["GET", "POST"])
def cap():
    if not require_admin():
        return jsonify({"error": "forbidden"}), 403
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        date = today()
        if request.method == "POST":
            payload = request.get_json(force=True, silent=True) or {}
            try:
                v = float(payload.get("dailyCap"))
            except (TypeError, ValueError):
                return jsonify({"error": "bad_value"}), 400
            cur.execute("INSERT INTO gbr_settings (biz_date, daily_cap) VALUES (%s,%s) "
                        "ON CONFLICT (biz_date) DO UPDATE SET daily_cap=EXCLUDED.daily_cap", (date, v))
        used = cap_used(cur, date)
        total = daily_cap_for(cur, date)
        return jsonify({"dailyCap": peso(total), "capUsed": peso(used), "capLeft": peso(max(0, total - used))})


@app.route("/api/admin/stop", methods=["GET", "POST"])
def stop():
    if not require_admin():
        return jsonify({"error": "forbidden"}), 403
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if request.method == "POST":
            payload = request.get_json(force=True, silent=True) or {}
            cur.execute("UPDATE gbr_kill_switch SET stopped=%s, note=%s, updated_at=%s WHERE id=1",
                        (bool(payload.get("stopped")), str(payload.get("note", ""))[:200], ms()))
        stopped, note = kill_switch(cur)
        return jsonify({"stopped": stopped, "note": note})


# ---------------------------------------------------------------- report
@app.route("/api/report", methods=["GET"])
def report():
    """Winnings per player for a date range. Same idea as the other games' verify-winner pages, so an
    agent (or the player, via the share token) can confirm a win without the admin password."""
    if not require_admin_or_share_token():
        return jsonify({"error": "forbidden"}), 403
    date_to = request.args.get("to") or today()
    date_from = request.args.get("from") or date_to
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT e.account, e.username, r.no, r.biz_date, e.place, e.prize "
            "FROM gbr_entries e JOIN gbr_races r ON r.id=e.race_id "
            "WHERE e.house=FALSE AND e.biz_date BETWEEN %s AND %s AND r.status='done' "
            "ORDER BY r.biz_date DESC, r.no DESC, e.place",
            (date_from, date_to),
        )
        rows = [{"account": r["account"], "name": r["username"], "race": r["no"], "date": r["biz_date"],
                 "place": r["place"], "prize": peso(r["prize"] or 0)} for r in cur.fetchall()]
        return jsonify({"from": date_from, "to": date_to, "game": GAME_NAME, "brand": BRAND_LABEL,
                        "rows": rows, "total": peso(sum(r["prize"] for r in rows))})


# ---------------------------------------------------------------- static
@app.after_request
def no_store(resp):
    # the page and its state must never be served stale (same reason as every other game here)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/health")
def health():
    return jsonify({"ok": True, "game": GAME_NAME, "brand": BRAND, "platform": PLATFORM,
                    "version": CONFIG["version"], "time": now().isoformat()})


@app.route("/report/<token>")
def report_page(token):
    if not REPORT_SHARE_TOKEN or not hmac.compare_digest(token, REPORT_SHARE_TOKEN):
        return "Not found", 404
    return send_from_directory(STATIC_DIR, "report.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(STATIC_DIR, path)


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))

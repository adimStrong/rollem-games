"""Games Tracker — every community game, every site, one conversion view.

Reads the game databases directly (the cg3 / fw2 `cg_sessions` + `cg_plays` tables) and the
shared wins-ledger for the agent-verified static games, and serves one page:
link made → player played → player won, per site, per day, with pesos paid.

Env (all optional except at least one source):
    DSN_GOPYESTA, DSN_POTS, DSN_TAMASA, DSN_WINFORLIFE, DSN_ROLLEM   Postgres DSN of each game
    DSN_LEDGER            wins-ledger Postgres (reachable inside the rollem-games Railway project)
    LEDGER_REPORT_GSPOT, LEDGER_REPORT_T2B   public /api/report/<brand>/<token> URLs — fallback
                          for the ledger brands when DSN_LEDGER is not reachable (local runs)
    REPORT_URLS           JSON {brand: public verify-winner page} shown as "Report" links
    CACHE_TTL             seconds (default 60) · TZ (default Asia/Manila) · SINCE (default 2026-09-01)
"""
import json
import os
import threading
import time
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg2
import psycopg2.extras
from flask import Flask, jsonify, send_from_directory

app = Flask(__name__, static_folder="static", static_url_path="/static")

TZ = ZoneInfo(os.environ.get("TZ", "Asia/Manila"))
CACHE_TTL = int(os.environ.get("CACHE_TTL", "60"))
SINCE = os.environ.get("SINCE", "2026-09-01")
REPORT_URLS = json.loads(os.environ.get("REPORT_URLS", "{}") or "{}")

# Fixed order = categorical colour slots on the page. Never reorder (CVD-safe adjacency).
BRANDS = [
    {"key": "gopyesta",   "label": "GoPyesta",     "game": "Lucky Ferris Wheel", "kind": "fw2",    "url": "https://gopyesta-production.up.railway.app"},
    {"key": "pots",       "label": "POTS",         "game": "Pearl Mine",         "kind": "cg3",    "url": "https://pots-production-f9dd.up.railway.app"},
    {"key": "tamasa",     "label": "Tamasa",       "game": "Swerte Lights",      "kind": "cg3",    "url": "https://tamasa-production.up.railway.app"},
    {"key": "winforlife", "label": "Win For Life", "game": "Spin For Life",      "kind": "cg3",    "url": "https://winforlife-production.up.railway.app"},
    {"key": "rollem",     "label": "Roll'em",      "game": "Roll It",            "kind": "cg3",    "url": "https://rollem-production.up.railway.app"},
    # gspot + t2b moved from the static pages to the cg3 backend on 2026-11-11/12 (home PC); gobetplay = GoBet Race, cg3.
    # A cg3 brand whose DSN_<KEY> is not set falls back to the ledger (wins only) when LEDGER_REPORT_<KEY> / DSN_LEDGER exists.
    {"key": "gspot",      "label": "GameSpot",     "game": "Power-Up Cards",     "kind": "cg3",    "url": "https://gspot-production.up.railway.app"},
    {"key": "t2b",        "label": "Time2Bet",     "game": "Time 2 Race",        "kind": "cg3",    "url": "https://t2b-production.up.railway.app"},
    {"key": "gobetplay",  "label": "GoBetPlay",    "game": "GoBet Race",         "kind": "cg3",    "url": "https://gobetplay-production.up.railway.app"},
]

_cache = {"at": 0.0, "payload": None}
_cfg_cache = {}
_lock = threading.Lock()


def today_str():
    return datetime.now(TZ).date().isoformat()


def _row():
    # cleared = prize money whose turnover condition is met (payable by Risk); won - cleared is still wagering
    return {"links": 0, "linked": 0, "plays": 0, "played": 0, "winners": 0, "won": 0.0, "seen": 0, "dep": 0.0, "cleared": 0.0}


def _q(dsn, sql, args=()):
    conn = psycopg2.connect(dsn, connect_timeout=10)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, args)
            return cur.fetchall()
    finally:
        conn.close()


def game_days(brand, dsn):
    """{biz_date: row} for a cg3 or fw2 game straight from its own tables."""
    days = {}
    for r in _q(dsn, "SELECT biz_date, COUNT(*) AS links, COUNT(DISTINCT user_id) AS linked "
                     "FROM cg_sessions WHERE biz_date >= %s GROUP BY 1", (SINCE,)):
        d = days.setdefault(r["biz_date"], _row())
        d["links"], d["linked"] = int(r["links"]), int(r["linked"])
    # cg3 games keep plays in cg_plays (amount_c centavos); the GoPyesta Lucky Ferris Wheel (fw2) keeps its spins in
    # fw_spins (amount pesos, status 'open' = cabin picked but not yet spun, 'paid' = spun and prize awarded).
    table, amount, paid = ("cg_plays", "amount_c/100.0", "status='paid'") if brand["kind"] == "cg3" else ("fw_spins", "amount", "status='paid'")
    rows = _q(dsn, f"SELECT biz_date, COUNT(*) AS plays, COUNT(DISTINCT user_id) AS played, "
                   f"COALESCE(SUM({amount}),0) AS won, COUNT(DISTINCT user_id) FILTER (WHERE {amount} > 0) AS winners, "
                   f"COALESCE(SUM(CASE WHEN seen > 0 THEN 1 ELSE 0 END),0) AS seen, "
                   f"COALESCE(SUM({amount}) FILTER (WHERE cleared_at IS NOT NULL),0) AS cleared "
                   f"FROM {table} WHERE {paid} AND biz_date >= %s GROUP BY 1", (SINCE,))
    deps = _q(dsn, f"SELECT biz_date, COALESCE(SUM(dep),0) AS dep FROM (SELECT biz_date, user_id, MAX(dep) AS dep "
                   f"FROM {table} WHERE {paid} AND biz_date >= %s GROUP BY 1,2) x GROUP BY 1", (SINCE,))
    for r in deps:
        days.setdefault(r["biz_date"], _row())["dep"] = float(r["dep"])
    for r in rows:
        d = days.setdefault(r["biz_date"], _row())
        d.update(plays=int(r["plays"]), played=int(r["played"]), won=float(r["won"]),
                 winners=int(r["winners"]), seen=int(r["seen"]), cleared=float(r["cleared"]))
    return days


def ledger_days(brand):
    """Agent-verified games only post their wins: one win per play, so plays = wins."""
    days = {}
    dsn = os.environ.get("DSN_LEDGER", "")
    wins = []
    if dsn:
        for r in _q(dsn, "SELECT amount, created_at, code, revoked FROM wins WHERE brand=%s", (brand["key"],)):
            wins.append({"amount": float(r["amount"]), "at": int(r["created_at"]), "code": r["code"],
                         "revoked": bool(r["revoked"])})
    else:
        url = os.environ.get("LEDGER_REPORT_" + brand["key"].upper(), "")
        if not url:
            raise ValueError("no DSN_LEDGER and no LEDGER_REPORT_" + brand["key"].upper())
        with urllib.request.urlopen(url, timeout=20) as resp:
            j = json.loads(resp.read().decode("utf-8"))
        for w in j.get("wins", []):
            wins.append({"amount": float(w["amount"]), "at": int(w["at"]), "code": w["code"],
                         "revoked": w.get("status") == "revoked"})
    per_day_codes = {}
    for w in wins:
        if w["revoked"]:
            continue
        bd = datetime.fromtimestamp(w["at"] / 1000, TZ).date().isoformat()
        if bd < SINCE:
            continue
        d = days.setdefault(bd, _row())
        d["plays"] += 1
        d["won"] += w["amount"]
        per_day_codes.setdefault(bd, set()).add(w["code"])
    for bd, codes in per_day_codes.items():
        days[bd]["played"] = days[bd]["winners"] = len(codes)
        days[bd]["seen"] = days[bd]["plays"]
        days[bd]["links"] = days[bd]["linked"] = None   # not tracked for static games
    return days


def game_config(brand):
    """Cap and live game name from the game's own public /api/config (cached 10 min)."""
    slot = _cfg_cache.get(brand["key"])
    if slot and time.time() - slot["at"] < 600:
        return slot["cfg"]
    cfg = {}
    try:
        with urllib.request.urlopen(brand["url"] + "/api/config", timeout=8) as resp:
            j = json.loads(resp.read().decode("utf-8"))
        cfg = {"cap": j.get("dailyCap"), "game": j.get("game") or brand["game"],
               "per_play": j.get("perPlay") or j.get("minDeposit"), "max_plays": j.get("maxPlays") or j.get("roundsPerDay"),
               "play_until": j.get("playUntil"), "dep_window": f'{j.get("depFrom","")}–{j.get("depTo","")}'}
    except Exception:
        cfg = {}
    _cfg_cache[brand["key"]] = {"at": time.time(), "cfg": cfg}
    return cfg


def build():
    out, ok = [], True
    for b in BRANDS:
        item = {k: b[k] for k in ("key", "label", "game", "kind", "url")}
        item["report_url"] = REPORT_URLS.get(b["key"], "")
        item["config"] = game_config(b)
        if item["config"].get("game"):
            item["game"] = item["config"]["game"]
        try:
            dsn = os.environ.get("DSN_" + b["key"].upper(), "")
            ledger_ok = bool(os.environ.get("DSN_LEDGER") or os.environ.get("LEDGER_REPORT_" + b["key"].upper()))
            if b["kind"] == "ledger" or (not dsn and ledger_ok):
                days = ledger_days(b)
                item["kind"] = "ledger"          # wins only on this source; the page says links are not tracked
            else:
                if not dsn:
                    raise ValueError("DSN_" + b["key"].upper() + " not set")
                days = game_days(b, dsn)
            item["ok"], item["error"] = True, None
        except Exception as exc:  # one dead source never blanks the page
            ok = False
            days = {}
            item["ok"], item["error"] = False, str(exc)[:160]
        item["days"] = days
        item["first_day"] = min(days) if days else None
        item["last_day"] = max(days) if days else None
        out.append(item)
    return {"ok": ok, "fetched_at": datetime.now(TZ).isoformat(), "today": today_str(),
            "since": SINCE, "brands": out}


def get_data(force=False):
    with _lock:
        if _cache["payload"] and not force and time.time() - _cache["at"] < CACHE_TTL:
            return _cache["payload"]
        payload = build()
        if payload["ok"] or not _cache["payload"]:
            _cache.update(at=time.time(), payload=payload)
            return payload
        # Partial failure: keep the last good source rows for the brands that failed this time.
        last = {b["key"]: b for b in _cache["payload"]["brands"]}
        for b in payload["brands"]:
            if not b["ok"] and b["key"] in last and last[b["key"]]["ok"]:
                b.update(days=last[b["key"]]["days"], first_day=last[b["key"]]["first_day"],
                         last_day=last[b["key"]]["last_day"], stale=True)
        _cache.update(at=time.time(), payload=payload)
        return payload


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/data")
def api_data():
    return jsonify(get_data())


@app.route("/api/refresh")
def api_refresh():
    return jsonify(get_data(force=True))


@app.route("/health")
def health():
    d = get_data()
    return jsonify({"ok": d["ok"], "sources": {b["key"]: (b["ok"], b["error"]) for b in d["brands"]},
                    "fetched_at": d["fetched_at"]})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False)

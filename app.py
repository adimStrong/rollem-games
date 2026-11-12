import calendar
import csv
import hashlib
import hmac
import io
import os
import time
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras
from flask import Flask, Response, jsonify, request, send_from_directory

app = Flask(__name__, static_folder=None)

DATABASE_URL = os.environ["DATABASE_URL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
SECRET_KEY = os.environ["SECRET_KEY"]
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

VALID_AMOUNTS = {10, 27, 57, 17, 37, 77}  # 17/37/77 = Gopyesta Palarong Pyesta tiers
# Gopyesta Lucky Ferris Wheel (2026-10-12) rolls a random P8-888 per spin, so gopyesta accepts any whole-peso amount in range
WHEEL_RANGE = (1, 1000)


def ph_date_ms(date_str: str, end: bool = False) -> int:
    """Epoch ms for midnight of a YYYY-MM-DD PH calendar date (PH = UTC+8). end=True -> midnight of the NEXT day (exclusive upper bound)."""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    if end:
        d = d + timedelta(days=1)
    utc_epoch_s = calendar.timegm(d.timetuple()) - 8 * 3600
    return utc_epoch_s * 1000


def date_range_clauses(args, clauses, params):
    date_from = args.get("from", "")
    date_to = args.get("to", "")
    if date_from:
        try:
            from_ms = ph_date_ms(date_from)
        except ValueError:
            pass
        else:
            clauses.append("created_at >= %s")
            params.append(from_ms)
    if date_to:
        try:
            to_ms = ph_date_ms(date_to, end=True)
        except ValueError:
            pass
        else:
            clauses.append("created_at < %s")
            params.append(to_ms)


RANGE_BRANDS = {"gopyesta", "pots", "tamasa", "gspot", "winforlife", "rollem", "t2b", "gobetplay"}  # pots (2026-11-06): Pearl Mine server-drawn ladder P7/P17 -- 7 is not in VALID_AMOUNTS; gspot (2026-11-09): Power-Up Cards pays P7/P17; winforlife P8.20/P16.50/P26 + rollem P7.50/P17.65/P27 (dev builds 2026-11-09)
# tamasa (2026-11-07): Swerte Lights pays P8.20 / P16.50 (centavo prizes), so `amount` is a decimal (DOUBLE PRECISION) from now on


def amount_ok(brand: str, amount: float) -> bool:
    if amount in VALID_AMOUNTS:
        return True
    return brand in RANGE_BRANDS and WHEEL_RANGE[0] <= amount <= WHEEL_RANGE[1]
# gobetplay (2026-11-11): GoBet Race pays P7 / P27 by finishing place. It posts server-side like the
# other platform-verified games, so it is NOT in TOKEN_BRANDS below -- its links carry no token.
VALID_BRANDS = {"gopyesta", "pots", "rollem", "winforlife", "cow", "tamasa", "gspot", "t2b", "gobetplay"}

# ---- the two backend-less (static) games: day expiry enforced at the payout boundary ----
# gspot and t2b have no server of their own, so their play window and one-day link expiry are gated in
# the browser (2026-11-11). A client gate alone can be defeated by a stale cached page, so the SAME rule
# is re-checked here, where the money is actually decided: a win whose link token is missing, forged,
# from another day, or outside the play window never becomes a row. The player might see the animation;
# they will not see a payout. The five backend-verified games post server-side with no token in the link
# and are untouched by this.
# The brand slug and the page's BRAND.key differ (the mismatch that once locked GameSpot's admin out),
# so the SALT key is mapped explicitly rather than derived from the slug.
TOKEN_BRANDS = {"gspot": "gamespot-cards", "t2b": "t2b"}
TOKEN_PLAY_FROM = os.environ.get("TOKEN_PLAY_FROM", "12:00")    # PH, inclusive
TOKEN_PLAY_UNTIL = os.environ.get("TOKEN_PLAY_UNTIL", "23:59")  # PH, inclusive
# OFF by default, and that is deliberate. This file can deploy before the gspot/t2b pages do, and the
# pages that are live until then still post pre-expiry 4-part links -- enforcing immediately would reject
# the wins of players who did nothing wrong. Set TOKEN_GATE=1 on the ledger service in the same batch
# that ships the new pages, not before.
TOKEN_GATE = os.environ.get("TOKEN_GATE", "") not in ("", "0", "off", "false")


def h36(s: str) -> str:
    """Python port of the games' h36() link hash (tools/h36.py). FNV-1a forward + a reversed pass, base36."""
    m = 0xFFFFFFFF
    h = 2166136261
    for ch in s:
        h ^= ord(ch)
        h = (h * 16777619) & m
    g = h
    for ch in reversed(s):
        g = (g ^ (ord(ch) * 31)) & m
        g = (g * 2246822519) & m

    def b36(n):
        d = "0123456789abcdefghijklmnopqrstuvwxyz"
        out = ""
        while n:
            out = d[n % 36] + out
            n //= 36
        return out or "0"

    return (b36(h) + b36(g))[:6]


def ph_now():
    """(YYYYMMDD, HH:MM) in PH time. UTC+8, no DST -- same convention as ph_date_ms."""
    t = time.gmtime(time.time() + 8 * 3600)
    return time.strftime("%Y%m%d", t), time.strftime("%H:%M", t)


def token_link_ok(brand: str, link: str):
    """(ok, reason) for a static game's posted link. The token is the fragment of the player URL:
    gspot  code.d<dep>.<nonce>.<YYYYMMDD>.<check>
    t2b    code.<r|v|c><dep>.<nonce>.<YYYYMMDD>.<check>
    Only the check hash and the date are inspected -- the deposit/offer parts are the agent's business."""
    if not TOKEN_GATE:
        return True, ""                      # inert until the new static pages are live (see TOKEN_GATE)
    key = TOKEN_BRANDS.get(brand)
    if not key:
        return True, ""                      # not a token-carrying brand: nothing to check
    frag = link.split("#", 1)[1] if "#" in link else ""
    parts = frag.lower().split(".")
    if len(parts) != 5:
        return False, "token"                # missing, or a pre-expiry 4-part link
    body = ".".join(parts[:4])
    if h36(body + "cg~" + key + "~26q4") != parts[4]:
        return False, "token"                # forged or edited (the date is inside the hashed body)
    day, hm = ph_now()
    if parts[3] != day:
        return False, "expired"
    if not (TOKEN_PLAY_FROM <= hm <= TOKEN_PLAY_UNTIL):
        return False, "closed"
    return True, ""


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Admin-Token"
    return response


@app.route("/api/win", methods=["OPTIONS"])
def win_options():
    return "", 204


def db():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    return conn


def init_db():
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS wins (
                id SERIAL PRIMARY KEY,
                brand TEXT NOT NULL,
                game TEXT NOT NULL,
                player_name TEXT NOT NULL DEFAULT '',
                code TEXT NOT NULL,
                amount INTEGER NOT NULL,
                link TEXT NOT NULL DEFAULT '',
                created_at BIGINT NOT NULL,
                claimed BOOLEAN NOT NULL DEFAULT FALSE,
                claimed_at BIGINT
            )
            """
        )
        cur.execute("ALTER TABLE wins ADD COLUMN IF NOT EXISTS claimed BOOLEAN NOT NULL DEFAULT FALSE")
        cur.execute("ALTER TABLE wins ADD COLUMN IF NOT EXISTS claimed_at BIGINT")
        cur.execute("ALTER TABLE wins ADD COLUMN IF NOT EXISTS revoked BOOLEAN NOT NULL DEFAULT FALSE")
        cur.execute("ALTER TABLE wins ADD COLUMN IF NOT EXISTS revoked_at BIGINT")
        cur.execute("ALTER TABLE wins ADD COLUMN IF NOT EXISTS note TEXT NOT NULL DEFAULT ''")
        # centavo prizes (tamasa Swerte Lights P8.20/P16.50): widen amount once; integers stored before stay exact
        cur.execute("SELECT data_type FROM information_schema.columns WHERE table_name='wins' AND column_name='amount'")
        row = cur.fetchone()
        if row and row[0] != "double precision":
            cur.execute("ALTER TABLE wins ALTER COLUMN amount TYPE DOUBLE PRECISION")
        cur.execute("CREATE INDEX IF NOT EXISTS wins_created_at_idx ON wins (created_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS wins_brand_idx ON wins (brand)")
        cur.execute("CREATE INDEX IF NOT EXISTS wins_claimed_idx ON wins (claimed)")


def admin_token() -> str:
    return hmac.new(SECRET_KEY.encode(), ADMIN_PASSWORD.encode(), hashlib.sha256).hexdigest()


def require_admin() -> bool:
    return hmac.compare_digest(request.headers.get("X-Admin-Token", ""), admin_token())


@app.route("/api/admin-login", methods=["POST"])
def admin_login():
    payload = request.get_json(force=True, silent=True) or {}
    if not hmac.compare_digest(payload.get("password", ""), ADMIN_PASSWORD):
        return jsonify({"error": "invalid"}), 403
    return jsonify({"token": admin_token()})


@app.route("/api/win", methods=["POST"])
def record_win():
    payload = request.get_json(force=True, silent=True) or {}
    brand = str(payload.get("brand", ""))[:40]
    game = str(payload.get("game", ""))[:80]
    name = str(payload.get("name", ""))[:120]
    code = str(payload.get("code", ""))[:80]
    link = str(payload.get("link", ""))[:300]
    try:
        amount = round(float(payload.get("amount")), 2)
        if amount != amount or amount in (float("inf"), float("-inf")):
            raise ValueError
        if amount == int(amount):
            amount = int(amount)   # whole-peso prizes keep their integer form (every brand before tamasa)
    except (TypeError, ValueError, OverflowError):
        return jsonify({"error": "bad amount"}), 400

    if brand not in VALID_BRANDS or not amount_ok(brand, amount) or not code:
        return jsonify({"error": "invalid payload"}), 400

    ok, why = token_link_ok(brand, link)
    if not ok:
        # Rejected, not stored: the static games' day/window rule, re-checked server-side.
        return jsonify({"error": why}), 400

    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO wins (brand, game, player_name, code, amount, link, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (brand, game, name, code, amount, link, int(time.time() * 1000)),
        )
    return jsonify({"ok": True})


@app.route("/api/now", methods=["GET"])
def server_now():
    """PH server clock for the backend-less static games (gspot, t2b). They gate play on the PH date and
    must not trust the player's device clock, which is one tap away from being wound back. No auth (it
    leaks the time) and deliberately NO database call, so it stays cheap and can never exhaust the
    connection pool. no-store matters: a cached clock would silently un-expire every link."""
    t = time.time()
    ph = time.gmtime(t + 8 * 3600)
    resp = jsonify({
        "ms": int(t * 1000),                          # epoch ms, UTC
        "date": time.strftime("%Y-%m-%d", ph),        # PH calendar date
        "day": time.strftime("%Y%m%d", ph),           # the token's day part
        "hm": time.strftime("%H:%M", ph),             # PH wall clock, for the admin hints
        "min": ph.tm_hour * 60 + ph.tm_min,           # PH minutes since midnight
        "tz": "Asia/Manila",
    })
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/api/wins", methods=["GET"])
def list_wins():
    if not require_admin():
        return jsonify({"error": "forbidden"}), 403
    brand = request.args.get("brand", "")
    status = request.args.get("status", "")  # "", "pending", "claimed"
    limit = min(int(request.args.get("limit", 200)), 1000)
    clauses, params = [], []
    if brand:
        clauses.append("brand=%s")
        params.append(brand)
    if status == "pending":
        clauses.append("claimed=FALSE AND revoked=FALSE")
    elif status == "claimed":
        clauses.append("claimed=TRUE")
    elif status == "revoked":
        clauses.append("revoked=TRUE")
    date_range_clauses(request.args, clauses, params)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM wins {where} ORDER BY created_at DESC LIMIT %s", params)
        rows = cur.fetchall()
    return jsonify({"wins": rows})


@app.route("/api/wins/export.csv", methods=["GET"])
def export_wins_csv():
    """CSV of wins (same brand/status filters as /api/wins) to hand to Risk for manual bonus distribution."""
    if not require_admin():
        return jsonify({"error": "forbidden"}), 403
    brand = request.args.get("brand", "")
    status = request.args.get("status", "")
    clauses, params = [], []
    if brand:
        clauses.append("brand=%s")
        params.append(brand)
    if status == "pending":
        clauses.append("claimed=FALSE AND revoked=FALSE")
    elif status == "claimed":
        clauses.append("claimed=TRUE")
    elif status == "revoked":
        clauses.append("revoked=TRUE")
    date_range_clauses(request.args, clauses, params)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM wins {where} ORDER BY created_at DESC", params)
        rows = cur.fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "date_ph", "brand", "game", "player_name", "code", "amount", "link", "status", "note"])
    for r in rows:
        status_label = "revoked" if r["revoked"] else ("sent_to_risk" if r["claimed"] else "pending")
        date_ph = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(r["created_at"] / 1000 + 8 * 3600))
        writer.writerow([r["id"], date_ph, r["brand"], r["game"], r["player_name"], r["code"], r["amount"], r["link"], status_label, r["note"]])

    filename = "wins-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime(time.time() + 8 * 3600)) + ".csv"
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.route("/api/wins/<int:win_id>/claim", methods=["POST"])
def claim_win(win_id):
    """Mark sent to Risk for manual bonus distribution (no more GCash send from here). Optional JSON {note}: batch ref / remarks."""
    if not require_admin():
        return jsonify({"error": "forbidden"}), 403
    payload = request.get_json(force=True, silent=True) or {}
    note = str(payload.get("note", ""))[:200]
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE wins SET claimed=TRUE, claimed_at=%s, revoked=FALSE, revoked_at=NULL, "
            "note=CASE WHEN %s<>'' THEN %s ELSE note END WHERE id=%s",
            (int(time.time() * 1000), note, note, win_id),
        )
        if cur.rowcount == 0:
            return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/wins/<int:win_id>/unclaim", methods=["POST"])
def unclaim_win(win_id):
    """Undo: back to pending (clears paid AND revoked)."""
    if not require_admin():
        return jsonify({"error": "forbidden"}), 403
    with db() as conn, conn.cursor() as cur:
        cur.execute("UPDATE wins SET claimed=FALSE, claimed_at=NULL, revoked=FALSE, revoked_at=NULL WHERE id=%s", (win_id,))
        if cur.rowcount == 0:
            return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/wins/<int:win_id>/revoke", methods=["POST"])
def revoke_win(win_id):
    """Void a win (JSON {note} = reason, e.g. 'turnover not met', 'duplicate account')."""
    if not require_admin():
        return jsonify({"error": "forbidden"}), 403
    payload = request.get_json(force=True, silent=True) or {}
    note = str(payload.get("note", ""))[:200]
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE wins SET revoked=TRUE, revoked_at=%s, claimed=FALSE, claimed_at=NULL, note=%s WHERE id=%s",
            (int(time.time() * 1000), note, win_id),
        )
        if cur.rowcount == 0:
            return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/wins/<int:win_id>", methods=["DELETE"])
def delete_win(win_id):
    """Hard-delete one erroneous row (e.g. test/dev data that leaked into production) --
    distinct from revoke, which marks a real-but-voided win and keeps the row for audit."""
    if not require_admin():
        return jsonify({"error": "forbidden"}), 403
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM wins WHERE id=%s", (win_id,))
        if cur.rowcount == 0:
            return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/wins/delete-by-player", methods=["POST"])
def delete_wins_by_player():
    """Bulk hard-delete, JSON {player_name, brand}: for cleaning up test/dev data that leaked
    into production (e.g. a local test run whose LEDGER_URL wasn't overridden). `brand` narrows
    the match so a generic test name doesn't collide with a real player on another brand."""
    if not require_admin():
        return jsonify({"error": "forbidden"}), 403
    payload = request.get_json(force=True, silent=True) or {}
    player_name = str(payload.get("player_name", "")).strip()
    brand = str(payload.get("brand", "")).strip()
    if not player_name:
        return jsonify({"error": "player_name required"}), 400
    with db() as conn, conn.cursor() as cur:
        if brand:
            cur.execute("DELETE FROM wins WHERE player_name=%s AND brand=%s", (player_name, brand))
        else:
            cur.execute("DELETE FROM wins WHERE player_name=%s", (player_name,))
        deleted = cur.rowcount
    return jsonify({"ok": True, "deleted": deleted})


# ---------- per-brand public winnings report (no password; the token in the URL is the key) ----------
# Agent brands (GameSpot, Win For Life, Roll'em, Time2Bet) have no server of their own, so their "Links & Winnings"
# equivalent lives here: every win posted for the brand in a PH date range. The token is derived from the admin password,
# so no new Railway variable is needed: base64url(HMAC-SHA256(ADMIN_PASSWORD, "report:" + brand))[:32].
BRAND_LABELS = {"gopyesta": "Gopyesta", "pots": "POTS", "rollem": "Roll'em", "winforlife": "Win For Life", "cow": "COW88",
                "tamasa": "TamasaPH", "gspot": "GameSpot", "t2b": "Time2Bet", "gobetplay": "GoBetPlay"}


def report_token(brand: str) -> str:
    import base64
    digest = hmac.new(ADMIN_PASSWORD.encode(), ("report:" + brand).encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")[:32]


ALL_REPORT = "all"   # /report/all/<token>: every site on one page, for the Risk team (2026-11-12)


def report_access_ok(brand: str, token: str) -> bool:
    return (brand in VALID_BRANDS or brand == ALL_REPORT) and bool(token) and hmac.compare_digest(token, report_token(brand))


@app.route("/report/<brand>/<token>", methods=["GET"])
def brand_report_page(brand, token):
    if not report_access_ok(brand, token):
        return "Not found", 404
    return send_from_directory(STATIC_DIR, "report-all.html" if brand == ALL_REPORT else "report-brand.html")


def _status_of(r):
    return "revoked" if r["revoked"] else ("sent_to_risk" if r["claimed"] else "pending")


def _totals(wins):
    valid = [w for w in wins if w["status"] != "revoked"]
    return {"wins": len(valid), "revoked": len(wins) - len(valid),
            "pending": sum(1 for w in valid if w["status"] == "pending"),
            "sent_to_risk": sum(1 for w in valid if w["status"] == "sent_to_risk"),
            "players": len({(w["player_name"] or w["code"]).lower() for w in valid}),
            "amount": round(sum(float(w["amount"]) for w in valid), 2),
            "pending_amount": round(sum(float(w["amount"]) for w in valid if w["status"] == "pending"), 2)}


@app.route("/api/report/<brand>/<token>", methods=["GET"])
def brand_report_api(brand, token):
    if not report_access_ok(brand, token):
        return jsonify({"error": "not found"}), 404
    clauses, params = [], []
    if brand != ALL_REPORT:
        clauses, params = ["brand=%s"], [brand]
    elif request.args.get("brand") in VALID_BRANDS:          # the all-sites page can narrow to one site
        clauses, params = ["brand=%s"], [request.args.get("brand")]
    status = request.args.get("status", "")
    if status == "pending":
        clauses.append("claimed=FALSE AND revoked=FALSE")
    elif status == "sent_to_risk":
        clauses.append("claimed=TRUE AND revoked=FALSE")
    elif status == "revoked":
        clauses.append("revoked=TRUE")
    date_range_clauses(request.args, clauses, params)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT id, brand, game, player_name, code, amount, created_at, claimed, revoked, note FROM wins {where} "
                    "ORDER BY created_at DESC LIMIT 5000", params)
        rows = cur.fetchall()
    wins = []
    for r in rows:
        wins.append({"id": r["id"], "brand": r["brand"], "label": BRAND_LABELS.get(r["brand"], r["brand"]), "game": r["game"],
                     "player_name": r["player_name"], "code": r["code"], "amount": r["amount"],
                     "at": r["created_at"], "status": _status_of(r), "note": r["note"]})
    totals = _totals(wins)
    if brand == ALL_REPORT:
        by_brand = []
        for b in sorted(VALID_BRANDS, key=lambda k: BRAND_LABELS.get(k, k).lower()):
            bw = [w for w in wins if w["brand"] == b]
            games = sorted({w["game"] for w in bw if w["game"]})
            by_brand.append({"brand": b, "label": BRAND_LABELS.get(b, b), "game": games[0] if len(games) == 1 else ", ".join(games),
                             **_totals(bw)})
        return jsonify({"brand": ALL_REPORT, "label": "All sites", "game": "", "wins": wins, "totals": totals,
                        "by_brand": by_brand, "brands": {b: BRAND_LABELS.get(b, b) for b in VALID_BRANDS}})
    game = wins[0]["game"] if wins else ""
    return jsonify({"brand": brand, "label": BRAND_LABELS.get(brand, brand), "game": game, "wins": wins, "totals": totals})


@app.route("/api/report-links", methods=["GET"])
def report_links():
    """Admin-only: the public report link of every brand (so the dashboard password holder can hand them out)."""
    if not require_admin():
        return jsonify({"error": "forbidden"}), 403
    base = request.url_root.rstrip("/")
    links = {b: f"{base}/report/{b}/{report_token(b)}" for b in sorted(VALID_BRANDS)}
    links[ALL_REPORT] = f"{base}/report/{ALL_REPORT}/{report_token(ALL_REPORT)}"
    return jsonify(links)


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(STATIC_DIR, path)


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

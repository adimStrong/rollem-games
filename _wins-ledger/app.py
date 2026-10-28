import csv
import hashlib
import hmac
import io
import os
import time

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


def amount_ok(brand: str, amount: int) -> bool:
    if amount in VALID_AMOUNTS:
        return True
    return brand == "gopyesta" and WHEEL_RANGE[0] <= amount <= WHEEL_RANGE[1]
VALID_BRANDS = {"gopyesta", "pots", "rollem", "winforlife", "cow", "tamasa", "gspot", "t2b"}


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
        amount = int(payload.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"error": "bad amount"}), 400

    if brand not in VALID_BRANDS or not amount_ok(brand, amount) or not code:
        return jsonify({"error": "invalid payload"}), 400

    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO wins (brand, game, player_name, code, amount, link, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (brand, game, name, code, amount, link, int(time.time() * 1000)),
        )
    return jsonify({"ok": True})


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


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(STATIC_DIR, path)


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

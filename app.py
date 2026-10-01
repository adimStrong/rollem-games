import hashlib
import hmac
import os
import time

import psycopg2
import psycopg2.extras
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder=None)

DATABASE_URL = os.environ["DATABASE_URL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
SECRET_KEY = os.environ["SECRET_KEY"]
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

VALID_AMOUNTS = {10, 27, 57}
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
                created_at BIGINT NOT NULL
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS wins_created_at_idx ON wins (created_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS wins_brand_idx ON wins (brand)")


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

    if brand not in VALID_BRANDS or amount not in VALID_AMOUNTS or not code:
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
    limit = min(int(request.args.get("limit", 200)), 1000)
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if brand:
            cur.execute(
                "SELECT * FROM wins WHERE brand=%s ORDER BY created_at DESC LIMIT %s",
                (brand, limit),
            )
        else:
            cur.execute("SELECT * FROM wins ORDER BY created_at DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
    return jsonify({"wins": rows})


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(STATIC_DIR, path)


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

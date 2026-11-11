"""POTS888 platform adapter — reads the pots-retention Postgres (Gobetplay-schema, see
C:\\Users\\us\\Pots\\pots-retention\\ledger.py): `users`, `deposits` (created_at = Manila-local TEXT,
order_status 'Success'), plus `bets_daily_category` — written by pots_link_turnover_sync.py (the
per-link slot-turnover job) in the same shape gopyesta's wheel reads. The game owns cg_* only.
"""
import psycopg2

PLATFORM_NOTE = "POTS888 (pots-retention DB) · turnover = bets_daily_category (slot = egame) na nila-link-sync tuwing ilang minuto"

_SCHEMA_LOCK_ID = 911727111


def ensure_schema(cur):
    """bets_daily_category normally already exists (sync job creates it); create if the game boots first."""
    cur.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_ID,))
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bets_daily_category (
            user_id BIGINT NOT NULL, biz_date TEXT NOT NULL, category TEXT NOT NULL,
            valid_bet DOUBLE PRECISION DEFAULT 0, bet_amount DOUBLE PRECISION DEFAULT 0,
            win_loss DOUBLE PRECISION DEFAULT 0, bet_count INTEGER DEFAULT 0, updated_at TEXT,
            PRIMARY KEY (user_id, biz_date, category)
        )
        """
    )


def find_user(cur, account: str):
    """Username, numeric user ID, or referral/in-game code (with or without a 2-letter brand prefix)."""
    q = account.strip()
    rq = q[2:] if len(q) > 2 and q[:2].isalpha() else q
    cur.execute(
        "SELECT user_id, account, COALESCE(real_name,'') AS real_name, COALESCE(referral_code,'') AS referral_code "
        "FROM users WHERE COALESCE(is_test,0)=0 AND COALESCE(user_type,'') NOT ILIKE 'test%%' "
        "AND (LOWER(account)=LOWER(%s) OR CAST(user_id AS TEXT)=%s OR LOWER(referral_code)=LOWER(%s) OR LOWER(referral_code)=LOWER(%s)) "
        "ORDER BY (LOWER(account)=LOWER(%s)) DESC LIMIT 1",
        (q, q, q, rq, q),
    )
    r = cur.fetchone()
    if not r:
        return None
    return {"user_id": int(r["user_id"]), "account": r["account"], "real_name": r["real_name"], "game_id": r["referral_code"]}


def window_deposits(cur, user_id, date, dep_from, dep_to):
    cur.execute(
        "SELECT amount, created_at FROM deposits WHERE user_id=%s AND biz_date=%s AND order_status='Success' "
        "AND substr(created_at,12,5) >= %s AND substr(created_at,12,5) < %s ORDER BY created_at",
        (user_id, date, dep_from, dep_to),
    )
    return [{"amount": float(r["amount"]), "at": r["created_at"][11:16]} for r in cur.fetchall()]


def slot_turnover(cur, user_id, date, cats):
    """(slot valid_bet today, other-category valid_bet today, latest sync time or None)."""
    try:
        cur.execute("SELECT category, COALESCE(valid_bet,0) AS valid_bet, updated_at FROM bets_daily_category "
                    "WHERE user_id=%s AND biz_date=%s", (user_id, date))
        rows = cur.fetchall()
    except psycopg2.Error:
        return 0.0, 0.0, None
    synced = max((r["updated_at"] or "" for r in rows), default=None) or None
    slot = sum(float(r["valid_bet"] or 0) for r in rows if r["category"] in cats)
    other = sum(float(r["valid_bet"] or 0) for r in rows if r["category"] not in cats)
    return slot, other, synced


def slot_bets_from(cur, user_id, date_from, cats):
    try:
        cur.execute("SELECT COALESCE(SUM(valid_bet),0) AS v FROM bets_daily_category "
                    "WHERE user_id=%s AND biz_date >= %s AND category = ANY(%s)", (user_id, date_from, cats))
        return float(cur.fetchone()["v"] or 0)
    except psycopg2.Error:
        return 0.0


def enrich_players(cur, players, date_from, date_to, dep_from, dep_to, cats):
    ids = list(players.keys())
    cur.execute("SELECT user_id, COALESCE(referral_code,'') AS rc FROM users WHERE user_id = ANY(%s)", (ids,))
    for r in cur.fetchall():
        players[r["user_id"]]["gameId"] = r["rc"]
    cur.execute("SELECT user_id, COALESCE(SUM(amount),0) AS dep_amount, COUNT(*) AS dep_count FROM deposits "
                "WHERE user_id = ANY(%s) AND biz_date BETWEEN %s AND %s AND order_status='Success' "
                "AND substr(created_at,12,5) >= %s AND substr(created_at,12,5) < %s GROUP BY user_id",
                (ids, date_from, date_to, dep_from, dep_to))
    for r in cur.fetchall():
        players[r["user_id"]].update(depAmount=float(r["dep_amount"]), depCount=int(r["dep_count"]))
    cur.execute("SELECT user_id, COALESCE(SUM(valid_bet),0) AS turnover FROM bets_daily_category "
                "WHERE user_id = ANY(%s) AND biz_date BETWEEN %s AND %s AND category = ANY(%s) GROUP BY user_id",
                (ids, date_from, date_to, cats))
    for r in cur.fetchall():
        players[r["user_id"]]["turnover"] = float(r["turnover"])

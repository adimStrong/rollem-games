"""TamasaPH platform adapter — reads tms-sync's tables in the `tms-members-db` Railway Postgres
(C:\\Users\\us\\tms-sync\\db.py + pull_player_daily.py):
  tms_members(member_id, username, fullname, ...)            roster
  tms_transactions(member_id, ts TIMESTAMP, trans_type 'Deposit', status, amount)   approved deposits
  tms_player_daily(member_id, date DATE, turnover, winloss, extracted_at)           per-player DAILY stake
CAVEAT (known, 2026-11-06): tms_player_daily.turnover is the member report's TOTAL stake for the day —
the Laravel back office has no per-category split in that report, so "slot only" cannot be enforced
from this table alone; WAGER_CATS is ignored here. The per-link job tms_link_turnover_sync.py refreshes
today's row for linked players only.
"""
import os

TMS_DEP_STATUS = os.environ.get("TMS_DEP_STATUS", "approved")   # LOWER(status) LIKE '<this>%'
PLATFORM_NOTE = "TamasaPH (tms-members-db) · turnover = tms_player_daily (kabuuang stake ng araw, walang per-category split)"


def ensure_schema(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS tms_player_daily (
            member_id BIGINT, date DATE, username TEXT,
            turnover NUMERIC(22,2), winloss NUMERIC(22,2),
            deposit NUMERIC(20,2), withdraw NUMERIC(20,2),
            deposit_count INTEGER, withdraw_count INTEGER,
            extracted_at TIMESTAMP,
            PRIMARY KEY (member_id, date)
        )
        """
    )


def find_user(cur, account: str):
    q = account.strip()
    cur.execute(
        "SELECT member_id, username, COALESCE(fullname,'') AS fullname FROM tms_members "
        "WHERE LOWER(username)=LOWER(%s) OR CAST(member_id AS TEXT)=%s "
        "ORDER BY (LOWER(username)=LOWER(%s)) DESC LIMIT 1",
        (q, q, q),
    )
    r = cur.fetchone()
    if not r:
        return None
    return {"user_id": int(r["member_id"]), "account": r["username"], "real_name": r["fullname"], "game_id": ""}


def window_deposits(cur, user_id, date, dep_from, dep_to):
    cur.execute(
        "SELECT amount, to_char(ts,'HH24:MI') AS hm FROM tms_transactions "
        "WHERE member_id=%s AND trans_type='Deposit' AND LOWER(COALESCE(status,'')) LIKE %s "
        "AND ts::date = %s::date AND to_char(ts,'HH24:MI') >= %s AND to_char(ts,'HH24:MI') < %s ORDER BY ts",
        (user_id, TMS_DEP_STATUS.lower() + "%", date, dep_from, dep_to),
    )
    return [{"amount": float(r["amount"] or 0), "at": r["hm"]} for r in cur.fetchall()]


def slot_turnover(cur, user_id, date, cats):
    cur.execute("SELECT COALESCE(turnover,0) AS t, extracted_at FROM tms_player_daily WHERE member_id=%s AND date=%s::date",
                (user_id, date))
    r = cur.fetchone()
    if not r:
        return 0.0, 0.0, None
    synced = r["extracted_at"].strftime("%Y-%m-%d %H:%M:%S") if r["extracted_at"] else None
    return float(r["t"] or 0), 0.0, synced


def slot_bets_from(cur, user_id, date_from, cats):
    cur.execute("SELECT COALESCE(SUM(turnover),0) AS v FROM tms_player_daily WHERE member_id=%s AND date >= %s::date",
                (user_id, date_from))
    return float(cur.fetchone()["v"] or 0)


def enrich_players(cur, players, date_from, date_to, dep_from, dep_to, cats):
    ids = list(players.keys())
    cur.execute(
        "SELECT member_id, COALESCE(SUM(amount),0) AS dep_amount, COUNT(*) AS dep_count FROM tms_transactions "
        "WHERE member_id = ANY(%s) AND trans_type='Deposit' AND LOWER(COALESCE(status,'')) LIKE %s "
        "AND ts::date BETWEEN %s::date AND %s::date AND to_char(ts,'HH24:MI') >= %s AND to_char(ts,'HH24:MI') < %s GROUP BY member_id",
        (ids, TMS_DEP_STATUS.lower() + "%", date_from, date_to, dep_from, dep_to),
    )
    for r in cur.fetchall():
        players[r["member_id"]].update(depAmount=float(r["dep_amount"]), depCount=int(r["dep_count"]))
    cur.execute("SELECT member_id, COALESCE(SUM(turnover),0) AS turnover FROM tms_player_daily "
                "WHERE member_id = ANY(%s) AND date BETWEEN %s::date AND %s::date GROUP BY member_id",
                (ids, date_from, date_to))
    for r in cur.fetchall():
        players[r["member_id"]]["turnover"] = float(r["turnover"])

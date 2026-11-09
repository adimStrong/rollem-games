"""TamasaPH platform adapter — reads the tamasa-retention Postgres (Railway project tamasa-retention, service
tms-postgres), which C:\\Users\\us\\Tamasa\\tamasa-retention fills from the TMS Cash Console (tms.adm666.com) in the
SAME Gobetplay/POTS schema the Pearl Mine adapter reads:
  users(user_id, account, real_name, user_type, is_test, referral_code=NULL)     roster
  deposits(order_num, user_id, amount, order_status 'Success' (= console Approved), created_at Manila-local TEXT, biz_date)
  bets_daily(user_id, biz_date, game_type 'ALL', valid_bet)   member report stake per player per day — the sync loop
                                                               re-pulls today + yesterday for EVERY active player every 10 min
  bets_daily_category(user_id, biz_date, category 'all', valid_bet, updated_at)
                                                               written only for today's LINKED players by link_turnover.py
                                                               (inside the same loop, every few minutes) — fresher, with a sync time
The console has no per-game-category split (slot vs casino), so WAGER_CATS for this platform is ['all']: every game counts.
Turnover used = the fresher of the two tables (both are cumulative-for-the-day stake from the same member report).
"""
import psycopg2

from platform_pots import ensure_schema, find_user, window_deposits  # same tables, same semantics  # noqa: F401

PLATFORM_NOTE = "TamasaPH (tamasa-retention DB) · turnover = member-report stake (LAHAT ng laro) na nire-refresh ng sync loop"
WAGER_VERB = "mag-bet"   # Taglish gate reason: "mag-bet pa ng ₱X" (any game counts)


def _daily(cur, user_id, date):
    cur.execute("SELECT COALESCE(SUM(valid_bet),0) AS v FROM bets_daily WHERE user_id=%s AND biz_date=%s AND game_type='ALL'",
                (user_id, date))
    r = cur.fetchone()
    return float(r["v"] or 0) if r else 0.0


def slot_turnover(cur, user_id, date, cats):
    """(turnover today, other-category turnover (always 0 here), latest link-sync time or None)."""
    linked, synced = None, None
    try:
        cur.execute("SELECT COALESCE(valid_bet,0) AS valid_bet, updated_at FROM bets_daily_category "
                    "WHERE user_id=%s AND biz_date=%s AND category='all'", (user_id, date))
        r = cur.fetchone()
        if r:
            linked, synced = float(r["valid_bet"] or 0), (r["updated_at"] or None)
    except psycopg2.Error:
        pass
    daily = _daily(cur, user_id, date)
    return max(daily, linked or 0.0), 0.0, synced


def slot_bets_from(cur, user_id, date_from, cats):
    cur.execute("SELECT COALESCE(SUM(valid_bet),0) AS v FROM bets_daily WHERE user_id=%s AND biz_date >= %s AND game_type='ALL'",
                (user_id, date_from))
    return float(cur.fetchone()["v"] or 0)


def enrich_players(cur, players, date_from, date_to, dep_from, dep_to, cats):
    ids = list(players.keys())
    cur.execute("SELECT user_id, COALESCE(SUM(amount),0) AS dep_amount, COUNT(*) AS dep_count FROM deposits "
                "WHERE user_id = ANY(%s) AND biz_date BETWEEN %s AND %s AND order_status='Success' "
                "AND substr(created_at,12,5) >= %s AND substr(created_at,12,5) < %s GROUP BY user_id",
                (ids, date_from, date_to, dep_from, dep_to))
    for r in cur.fetchall():
        players[r["user_id"]].update(depAmount=float(r["dep_amount"]), depCount=int(r["dep_count"]))
    cur.execute("SELECT user_id, COALESCE(SUM(valid_bet),0) AS turnover FROM bets_daily "
                "WHERE user_id = ANY(%s) AND biz_date BETWEEN %s AND %s AND game_type='ALL' GROUP BY user_id",
                (ids, date_from, date_to))
    for r in cur.fetchall():
        players[r["user_id"]]["turnover"] = float(r["turnover"])

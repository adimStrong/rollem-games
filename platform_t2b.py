"""Time2Bet platform adapter — reads the `t2bet-retention` Railway Postgres (project
f950319d-4187-42bb-862a-16d800f0d240, service "t2b-postgres") over its PUBLIC TCP-proxy host. The service's
own DATABASE_URL is the `.internal` name and does NOT work cross-project, which is the exact trap this
project hit on gopyesta — always compose from RAILWAY_TCP_PROXY_DOMAIN/PORT + PG* (see
C:\\tmp\\gobetplay_pg_dsn.txt).

Schema verified live on 2026-11-11 (identical to GoBetplay's), and it is the familiar Gobetplay/POTS shape for the two tables that
matter here, so those readers are imported rather than re-written:
  users(user_id, account, real_name, referral_code, user_type, is_test)
  deposits(user_id, amount, order_status 'Success', created_at Manila-local TEXT, biz_date)

TURNOVER IS THE ONE REAL DIFFERENCE, and it is why this file exists instead of reusing platform_tms.py:
  * there is NO `bets_daily_category` table at all (POTS has one, written by its link-sync job);
  * `bets_daily(user_id, biz_date, game_type, valid_bet)` here holds ONE rolled-up row per player-day
    at game_type='ALL' (unlike GoBetplay, where it is one row per provider).
These readers SUM bets_daily with NO game_type filter, which is deliberately correct for both shapes:
it adds up a single 'ALL' row here, and 39 provider rows on GoBetplay. Do not re-add a
game_type='ALL' filter -- that is what would break the GoBetplay copy of this file.

Because `game_type` is a provider and not a category, there is no slot-vs-casino split to filter on:
every game counts, so run this service with WAGER_CATS=all and keep the player copy saying "turnover"
rather than "slot turnover".
"""
from platform_pots import find_user, window_deposits  # identical users/deposits shape  # noqa: F401

PLATFORM_NOTE = ("Time2Bet (t2bet-retention DB) · turnover = bets_daily valid_bet, lahat ng laro; "
                 "walang slot/casino split sa console")
WAGER_VERB = "mag-bet"   # Taglish gate reason: "mag-bet pa ng ₱X" (any game counts)


def ensure_schema(cur):
    """Deliberately a no-op.

    This is somebody else's database: the retention sync owns every table in it. The game's own state
    lives in gbr_* tables created by app.py's init_db(), and nothing here should add or alter a platform
    table. (platform_pots.ensure_schema() would CREATE an empty bets_daily_category, which this platform
    does not use and which would then look like a real but permanently empty turnover source.)
    """
    return


def slot_turnover(cur, user_id, date, cats):
    """(turnover today, other-category turnover, latest sync time or None).

    Summed over every provider. `cats` is ignored: this platform cannot split slot from casino, so the
    second element is always 0.0 rather than pretending some of the stake was 'other'.
    """
    cur.execute(
        "SELECT COALESCE(SUM(valid_bet),0) AS v, MAX(biz_date) AS d FROM bets_daily "
        "WHERE user_id=%s AND biz_date=%s",
        (user_id, date),
    )
    r = cur.fetchone()
    return (float(r["v"] or 0) if r else 0.0), 0.0, None


def slot_bets_from(cur, user_id, date_from, cats):
    cur.execute(
        "SELECT COALESCE(SUM(valid_bet),0) AS v FROM bets_daily WHERE user_id=%s AND biz_date >= %s",
        (user_id, date_from),
    )
    return float(cur.fetchone()["v"] or 0)


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
    cur.execute("SELECT user_id, COALESCE(SUM(valid_bet),0) AS turnover FROM bets_daily "
                "WHERE user_id = ANY(%s) AND biz_date BETWEEN %s AND %s GROUP BY user_id",
                (ids, date_from, date_to))
    for r in cur.fetchall():
        players[r["user_id"]]["turnover"] = float(r["turnover"])

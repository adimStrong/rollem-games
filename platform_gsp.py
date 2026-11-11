"""GameSpot platform adapter — reads the `gsp-retention` Railway Postgres (project
fcbe28b7-d117-4f07-bff8-75e854dcb21a, service "gsp-postgres") over its PUBLIC TCP-proxy host. The
service's own DATABASE_URL is the `.internal` name and does NOT work cross-project.

TWO TRAPS specific to this database, both verified live on 2026-11-11:
  * the role and database are both **gsp**, not postgres/railway -- read POSTGRES_USER/POSTGRES_DB
    rather than assuming the Railway defaults;
  * the TCP proxy does **not** speak SSL. `sslmode=require` fails with "server does not support SSL";
    use `sslmode=disable`. Every other brand's DB in this project takes `require`, so this is the odd
    one out. The composed DSN lives in C:/tmp/gspot_pg_dsn.txt.

Schema is the familiar POTS/Time2Bet shape, so those readers are imported rather than re-written:
  users(user_id, account, real_name, referral_code, user_type, is_test)
  deposits(user_id, amount, order_status 'Success', created_at Manila-local TEXT, biz_date)

TURNOVER: `bets_daily(user_id, biz_date, game_type, valid_bet)` holds ONE rolled-up row per
player-day at game_type='ALL' (5,848 rows, all 'ALL'), and there is NO `bets_daily_category` table --
exactly like Time2Bet. These readers SUM bets_daily with NO game_type filter, which is deliberately
correct for that shape and also for GoBetplay's one-row-per-provider shape. Do not add a
game_type='ALL' filter: it would break the shared copy of this file.

Because game_type carries no category, there is no slot-vs-casino split to filter on: every game
counts, so run this service with WAGER_CATS=all and keep the player copy saying "turnover" rather
than "slot turnover".
"""
from platform_pots import find_user, window_deposits  # identical users/deposits shape  # noqa: F401

PLATFORM_NOTE = ("GameSpot (gsp-retention DB) · turnover = bets_daily valid_bet, lahat ng laro; "
                 "walang slot/casino split sa console")
WAGER_VERB = "mag-bet"   # Taglish gate reason: "mag-bet pa ng ₱X" (any game counts)


def ensure_schema(cur):
    """Deliberately a no-op.

    This is somebody else's database: the retention sync owns every table in it. The game's own state
    lives in cg_* tables created by app.py's init_db(), and nothing here should add or alter a platform
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

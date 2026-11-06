"""Seed a throwaway Postgres with TamasaPH-shaped tables (tamasa-retention = Gobetplay/POTS schema subset) + today's rows.
Usage: python tests/fixture_tms.py [dsn]   (default postgresql://postgres:cgtest@localhost:55442/cg)
PER_PLAY=200, TURNOVER_MULT=1, WAGER_CATS=all, window 13:00-21:00. Turnover = the fresher of bets_daily (game_type ALL,
loop-refreshed) and bets_daily_category (category 'all', link-sync refreshed):
  juan123  (1001) dep 400 @13:30 (+300 @10:00 outside window, +999 Failed) -> 2 plays; bets_daily 350 but link row 400 -> 400:
           play1 (need 200) & play2 (need 400) unlocked
  maria_x  (1002) dep 200 @14:00 -> 1 play; bets_daily 100, no link row -> turnover-locked
  tester   (1003) is_test=1 -> never found
  pedro    (1004) dep 2000 @16:00 -> 10 -> capped at MAX_PLAYS 5; bets 5000 -> all unlocked (drives the cap test)
  uitest1  (1005) dep 600 @15:00 -> 3 plays; bets_daily 600 only (fallback path, syncedAt null) -> all 3 unlocked (UI test)
  nodep    (1006) no deposit today -> 0 plays
"""
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg2

TZ = ZoneInfo("Asia/Manila")
today = datetime.now(TZ).strftime("%Y-%m-%d")
dsn = sys.argv[1] if len(sys.argv) > 1 else "postgresql://postgres:cgtest@localhost:55442/cg"
c = psycopg2.connect(dsn)
c.autocommit = True
cur = c.cursor()
cur.execute("DROP TABLE IF EXISTS users, deposits, bets_daily, bets_daily_category, cg_sessions, cg_settings, cg_plays, cg_kill_switch")
cur.execute("""CREATE TABLE users (user_id INTEGER PRIMARY KEY, account TEXT, referral_code TEXT, real_name TEXT,
  user_type TEXT, is_test INTEGER DEFAULT 0)""")
cur.execute("""CREATE TABLE deposits (order_num TEXT PRIMARY KEY, user_id INTEGER, user_account TEXT,
  amount DOUBLE PRECISION NOT NULL, order_status TEXT, created_at TEXT NOT NULL, biz_date TEXT NOT NULL)""")
cur.execute("""CREATE TABLE bets_daily (user_id INTEGER, biz_date TEXT, game_type TEXT, valid_bet DOUBLE PRECISION,
  win_loss DOUBLE PRECISION, bet_count INTEGER, PRIMARY KEY (user_id, biz_date, game_type))""")
cur.execute("""CREATE TABLE bets_daily_category (user_id BIGINT NOT NULL, biz_date TEXT NOT NULL, category TEXT NOT NULL,
  valid_bet DOUBLE PRECISION DEFAULT 0, bet_amount DOUBLE PRECISION DEFAULT 0, win_loss DOUBLE PRECISION DEFAULT 0,
  bet_count INTEGER DEFAULT 0, updated_at TEXT, PRIMARY KEY (user_id, biz_date, category))""")
cur.executemany("INSERT INTO users VALUES (%s,%s,%s,%s,%s,%s)", [
    (1001, "juan123", None, "Juan Dela Cruz", "Normal Account", 0),
    (1002, "maria_x", None, "", "Normal Account", 0),
    (1003, "tester", None, "QA", "Test Account", 1),
    (1004, "pedro", None, "Pedro P", "Normal Account", 0),
    (1005, "uitest1", None, "UI Tester", "Normal Account", 0),
    (1006, "nodep", None, "No Deposit", "Normal Account", 0),
])
D = lambda n, uid, acct, amt, st, hm, d=today: (n, uid, acct, amt, st, f"{d} {hm}:00", d)
cur.executemany("INSERT INTO deposits VALUES (%s,%s,%s,%s,%s,%s,%s)", [
    D("o1", 1001, "juan123", 400, "Success", "13:30"),
    D("o2", 1001, "juan123", 300, "Success", "10:00"),   # outside window (before 13:00)
    D("o3", 1001, "juan123", 999, "Failed", "16:00"),    # not Success
    D("o4", 1001, "juan123", 200, "Success", "21:00"),   # exactly 21:00 -> excluded (window end exclusive)
    D("o5", 1002, "maria_x", 200, "Success", "14:00"),
    D("o6", 1003, "tester", 1000, "Success", "14:00"),
    D("o7", 1004, "pedro", 2000, "Success", "16:00"),
    D("o8", 1005, "uitest1", 600, "Success", "15:00"),
])
cur.executemany("INSERT INTO bets_daily VALUES (%s,%s,%s,%s,%s,%s)", [
    (1001, today, "ALL", 350, -20, 0),
    (1002, today, "ALL", 100, -5, 0),
    (1004, today, "ALL", 5000, -100, 0),
    (1005, today, "ALL", 600, -30, 0),
])
cur.executemany("INSERT INTO bets_daily_category VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", [
    (1001, today, "all", 400, 400, -25, 0, f"{today} 16:05:00"),   # fresher than bets_daily's 350
])
print("seeded TMS fixture for", today, "at", dsn)

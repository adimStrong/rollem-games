"""Seed a throwaway Postgres with POTS-shaped tables (pots-retention / Gobetplay schema subset) + today's rows.
Usage: python tests/fixture_pots.py [dsn]   (default postgresql://postgres:cgtest@localhost:55441/cg)
PER_PLAY=150, TURNOVER_MULT=1, WAGER_CATS=egame, window 12:00-21:00:
  juan123  dep 300 @13:30 (+500 @10:00 outside window, +999 Failed) -> 2 plays; egame 500 -> play1 (need 150) & play2 (need 300) unlocked
  maria_x  dep 150 @14:00 -> 1 play; egame 100 < 150 -> turnover-locked
  pedro    dep 1500 @16:00 -> 10 -> capped at MAX_PLAYS 5; egame 5000 -> all unlocked (drives the cap test)
  tester   is_test=1 -> never found
  uitest1  dep 450 @15:00 -> 3 plays; egame 450 -> all 3 unlocked (UI test)
  nodep    no deposit today -> 0 plays
  juan123 also has referral_code 'AbC123' (lookup by game id 'AbC123' or 'PTAbC123')
"""
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg2

TZ = ZoneInfo("Asia/Manila")
today = datetime.now(TZ).strftime("%Y-%m-%d")
dsn = sys.argv[1] if len(sys.argv) > 1 else "postgresql://postgres:cgtest@localhost:55441/cg"
c = psycopg2.connect(dsn)
c.autocommit = True
cur = c.cursor()
cur.execute("DROP TABLE IF EXISTS users, deposits, bets_daily_category, cg_sessions, cg_settings, cg_plays, cg_kill_switch")
cur.execute("""CREATE TABLE users (user_id INTEGER PRIMARY KEY, account TEXT UNIQUE, referral_code TEXT, real_name TEXT,
  user_type TEXT, is_test INTEGER DEFAULT 0)""")
cur.execute("""CREATE TABLE deposits (order_num TEXT PRIMARY KEY, user_id INTEGER, user_account TEXT,
  amount DOUBLE PRECISION NOT NULL, order_status TEXT, created_at TEXT NOT NULL, biz_date TEXT NOT NULL)""")
cur.execute("""CREATE TABLE bets_daily_category (user_id BIGINT NOT NULL, biz_date TEXT NOT NULL, category TEXT NOT NULL,
  valid_bet DOUBLE PRECISION DEFAULT 0, bet_amount DOUBLE PRECISION DEFAULT 0, win_loss DOUBLE PRECISION DEFAULT 0,
  bet_count INTEGER DEFAULT 0, updated_at TEXT, PRIMARY KEY (user_id, biz_date, category))""")
cur.executemany("INSERT INTO users VALUES (%s,%s,%s,%s,%s,%s)", [
    (1, "juan123", "AbC123", "Juan Dela Cruz", "Normal Account", 0),
    (2, "maria_x", "mX9", "", "Normal Account", 0),
    (3, "tester", "tst", "QA", "Test Account", 1),
    (4, "pedro", "pdr", "Pedro P", "Normal Account", 0),
    (5, "uitest1", "ui1", "UI Tester", "Normal Account", 0),
    (6, "nodep", "nd", "No Deposit", "Normal Account", 0),
])
D = lambda n, uid, acct, amt, st, hm, d=today: (n, uid, acct, amt, st, f"{d} {hm}:00", d)
cur.executemany("INSERT INTO deposits VALUES (%s,%s,%s,%s,%s,%s,%s)", [
    D("o1", 1, "juan123", 300, "Success", "13:30"),
    D("o2", 1, "juan123", 500, "Success", "10:00"),   # outside window (before 12:00)
    D("o3", 1, "juan123", 999, "Failed", "16:00"),    # not Success
    D("o4", 1, "juan123", 300, "Success", "21:00"),   # exactly 21:00 -> excluded (window end exclusive)
    D("o5", 2, "maria_x", 150, "Success", "14:00"),
    D("o6", 3, "tester", 1000, "Success", "14:00"),
    D("o7", 4, "pedro", 1500, "Success", "16:00"),
    D("o8", 5, "uitest1", 450, "Success", "15:00"),
])
cur.executemany("INSERT INTO bets_daily_category VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", [
    (1, today, "egame", 500, 520, -40, 30, f"{today} 16:05:00"),
    (1, today, "casino", 400, 400, 10, 8, f"{today} 16:05:00"),    # must NOT count (slot only)
    (1, today, "fishing", 5000, 5000, 0, 100, f"{today} 16:05:00"),
    (2, today, "egame", 100, 100, -10, 6, f"{today} 16:05:00"),
    (4, today, "egame", 5000, 5000, -100, 50, f"{today} 16:05:00"),
    (5, today, "egame", 450, 450, -30, 10, f"{today} 16:05:00"),
])
print("seeded POTS fixture for", today, "at", dsn)

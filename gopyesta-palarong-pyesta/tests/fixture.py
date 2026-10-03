"""Seed the throwaway Postgres with gpr-shaped tables + today's sample data (PHT).
Juan123: 2 qualifying deposits (150 @13:30, 250 @15:10) -> cumulative reqs 450 / 1200; turnover 1300 -> both unlocked.
maria_x: 120 @14:00 + 200 @15:00 -> reqs 360 / 960; turnover 400 -> entry 1 unlocked, entry 2 LOCKED.
pedro:   1000 @16:00 -> req 3000; turnover 5000 -> unlocked (used for the cap test)."""
import psycopg2
from datetime import datetime
from zoneinfo import ZoneInfo
TZ = ZoneInfo("Asia/Manila")
today = datetime.now(TZ).strftime("%Y-%m-%d")
dsn = "postgresql://postgres:cgtest@localhost:55432/cg"
c = psycopg2.connect(dsn); c.autocommit = True; cur = c.cursor()
cur.execute("DROP TABLE IF EXISTS users, deposits, bets_daily_category, cg_sessions, cg_plays, cg_settings")
cur.execute("""CREATE TABLE users (user_id INTEGER PRIMARY KEY, account TEXT UNIQUE, real_name TEXT, is_test INTEGER DEFAULT 0)""")
cur.execute("""CREATE TABLE deposits (order_num TEXT PRIMARY KEY, user_id INTEGER, user_account TEXT,
  amount DOUBLE PRECISION NOT NULL, order_status TEXT, created_at TEXT NOT NULL, biz_date TEXT NOT NULL)""")
cur.execute("""CREATE TABLE bets_daily_category (user_id INTEGER NOT NULL, biz_date TEXT NOT NULL, category TEXT NOT NULL,
  valid_bet NUMERIC DEFAULT 0, bet_amount NUMERIC DEFAULT 0, win_loss NUMERIC DEFAULT 0, bet_count INTEGER DEFAULT 0, updated_at TEXT,
  PRIMARY KEY (user_id, biz_date, category))""")
cur.executemany("INSERT INTO users VALUES (%s,%s,%s,%s)", [
    (1, "Juan123", "Juan Dela Cruz", 0), (2, "maria_x", "", 0), (3, "tester", "QA", 1), (4, "pedro", "Pedro P", 0)])
D = lambda n, uid, acct, amt, st, hm, d=today: (n, uid, acct, amt, st, f"{d} {hm}:00", d)
cur.executemany("INSERT INTO deposits VALUES (%s,%s,%s,%s,%s,%s,%s)", [
    D("o1", 1, "Juan123", 150, "Success", "13:30"),
    D("o2", 1, "Juan123", 250, "Success", "15:10"),
    D("o3", 1, "Juan123", 500, "Success", "10:00"),   # outside window
    D("o4", 1, "Juan123", 999, "Failed", "16:00"),    # not Success
    D("o5", 1, "Juan123", 300, "Success", "21:00"),   # exactly 21:00 -> excluded (window end exclusive)
    D("o6", 1, "Juan123", 80, "Success", "16:20"),    # below ₱100 -> no entry
    D("o7", 2, "maria_x", 120, "Success", "14:00"),
    D("o8", 2, "maria_x", 200, "Success", "15:00"),
    D("o9", 3, "tester", 1000, "Success", "14:00"),   # test account
    D("o10", 4, "pedro", 1000, "Success", "16:00"),
])
cur.executemany("INSERT INTO bets_daily_category VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", [
    (1, today, "egame", 900, 950, -40, 30, f"{today} 16:05:00"),
    (1, today, "casino", 400, 400, 10, 8, f"{today} 16:05:00"),
    (1, today, "fishing", 5000, 5000, 0, 100, f"{today} 16:05:00"),  # must NOT count
    (2, today, "egame", 400, 400, -20, 12, f"{today} 16:05:00"),
    (4, today, "egame", 5000, 5000, -100, 50, f"{today} 16:05:00"),
])
print("seeded for", today)

"""Seed a throwaway Postgres with Tamasa-shaped tables (tms-sync db.py / pull_player_daily.py) + today's rows.
Usage: python tests/fixture_tms.py [dsn]   (default postgresql://postgres:cgtest@localhost:55442/cg)
PER_PLAY=200, TURNOVER_MULT=1, window 13:00-21:00:
  juan123  dep 400 @13:30 (+300 @10:00 outside window, +999 Pending) -> 2 plays; turnover 400 -> play1 (200) & play2 (400) unlocked
  maria_x  dep 200 @14:00 -> 1 play; turnover 100 -> locked
  pedro    dep 2000 @16:00 -> 10 -> capped at 5; turnover 5000
  uitest1  dep 600 @15:00 -> 3 plays; turnover 600 -> all unlocked
  nodep    no deposit
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
cur.execute("DROP TABLE IF EXISTS tms_members, tms_transactions, tms_player_daily, cg_sessions, cg_settings, cg_plays, cg_kill_switch")
cur.execute("CREATE TABLE tms_members (member_id BIGINT PRIMARY KEY, username TEXT, fullname TEXT)")
cur.execute("""CREATE TABLE tms_transactions (txn_id BIGINT PRIMARY KEY, ts TIMESTAMP, member_id BIGINT, username TEXT,
  trans_type TEXT, status TEXT, amount NUMERIC(20,4))""")
cur.execute("""CREATE TABLE tms_player_daily (member_id BIGINT, date DATE, username TEXT, turnover NUMERIC(22,2), winloss NUMERIC(22,2),
  deposit NUMERIC(20,2), withdraw NUMERIC(20,2), deposit_count INTEGER, withdraw_count INTEGER, extracted_at TIMESTAMP,
  PRIMARY KEY (member_id, date))""")
cur.executemany("INSERT INTO tms_members VALUES (%s,%s,%s)", [
    (1001, "juan123", "Juan Dela Cruz"), (1002, "maria_x", ""), (1004, "pedro", "Pedro P"), (1005, "uitest1", "UI Tester"), (1006, "nodep", "No Deposit")])
T = lambda n, mid, acct, amt, st, hm, typ="Deposit", d=today: (n, f"{d} {hm}:00", mid, acct, typ, st, amt)
cur.executemany("INSERT INTO tms_transactions VALUES (%s,%s,%s,%s,%s,%s,%s)", [
    T(1, 1001, "juan123", 400, "Approved", "13:30"),
    T(2, 1001, "juan123", 300, "Approved", "10:00"),      # outside window
    T(3, 1001, "juan123", 999, "Pending", "16:00"),       # not approved
    T(4, 1001, "juan123", 500, "Approved", "17:00", "Withdrawal"),  # not a deposit
    T(5, 1002, "maria_x", 200, "Approved", "14:00"),
    T(7, 1004, "pedro", 2000, "Approved", "16:00"),
    T(8, 1005, "uitest1", 600, "Approved", "15:00"),
])
cur.executemany("INSERT INTO tms_player_daily VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", [
    (1001, today, "juan123", 400, -20, 400, 0, 1, 0, f"{today} 16:05:00"),
    (1002, today, "maria_x", 100, -5, 200, 0, 1, 0, f"{today} 16:05:00"),
    (1004, today, "pedro", 5000, -100, 2000, 0, 1, 0, f"{today} 16:05:00"),
    (1005, today, "uitest1", 600, -30, 600, 0, 1, 0, f"{today} 16:05:00"),
])
print("seeded TMS fixture for", today, "at", dsn)

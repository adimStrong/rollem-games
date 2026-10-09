"""A tiny in-memory stand-in for psycopg2, good enough for this service's queries.

There is no Postgres on the machine this was built on, so the alternative was testing
nothing above the pure functions. This fake answers the specific statements app.py issues
and keeps the rows in dicts, which lets the real Flask routes, the real gate order and the
real server-side draw run end to end.

What it does NOT prove: that the SQL is valid Postgres, that the schema matches, or that
UNIQUE (user_id, biz_date, entry_no) really stops a double-pay under concurrency. It fakes
that constraint rather than enforcing it the way a database would. Those need a real
database; check_sql.py gates the syntax and nothing here replaces a live run.
"""
import re

# every mutable row store the fake owns
STATE = {
    "users": {},        # account.lower() -> {user_id, account, real_name}
    "deposits": [],     # {user_id, biz_date, amount, created_at, order_status}
    "turnover": {},     # (user_id, biz_date) -> valid_bet
    "synced_at": "2026-10-09 20:30:00",
    "sessions": {},     # code -> row
    "picks": {},        # (user_id, biz_date) -> {cabin, tier}
    "plays": [],        # {user_id, biz_date, entry_no, step, prize, tier, played_at, account, code}
    "settings": {},     # biz_date -> daily_cap
    "fail_turnover": False,   # make the category table unreadable
}


def reset():
    STATE.update({"users": {}, "deposits": [], "turnover": {}, "sessions": {},
                  "picks": {}, "plays": [], "settings": {}, "fail_turnover": False})


def add_user(user_id, account, real_name=""):
    STATE["users"][account.lower()] = {"user_id": user_id, "account": account,
                                       "real_name": real_name}


def add_deposit(user_id, biz_date, amount, at="14:30"):
    STATE["deposits"].append({"user_id": user_id, "biz_date": biz_date,
                              "amount": float(amount), "order_status": "Success",
                              "created_at": f"{biz_date} {at}:00"})


def set_turnover(user_id, biz_date, amount):
    STATE["turnover"][(user_id, biz_date)] = float(amount)


class Error(Exception):
    pass


class IntegrityError(Error):
    pass


class _Cur:
    def __init__(self):
        self._rows = []

    # context-manager form used by `with conn.cursor() as cur`
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def close(self):
        pass

    def execute(self, sql, args=None):
        s = " ".join(sql.split())
        a = args or ()
        self._rows = []

        if re.match(r"(?i)^(CREATE|ALTER|DROP)", s):
            return

        if "FROM users WHERE LOWER(account)" in s:
            u = STATE["users"].get(str(a[0]).strip().lower())
            self._rows = [dict(u)] if u else []
            return

        if "FROM deposits WHERE user_id" in s:
            uid, date, lo, hi = a
            out = []
            for d in STATE["deposits"]:
                if d["user_id"] != uid or d["biz_date"] != date:
                    continue
                if d["order_status"] != "Success":
                    continue
                hm = d["created_at"][11:16]
                if lo <= hm < hi:
                    out.append({"amount": d["amount"], "created_at": d["created_at"]})
            self._rows = sorted(out, key=lambda r: r["created_at"])
            return

        if "FROM bets_daily_category" in s:
            if STATE["fail_turnover"]:
                raise Error("relation bets_daily_category does not exist")
            uid, date, _cats = a
            self._rows = [{"valid_bet": STATE["turnover"].get((uid, date), 0.0),
                           "synced_at": STATE["synced_at"]}]
            return

        if "FROM cg_plays WHERE user_id" in s:
            uid, date = a
            self._rows = sorted(
                [dict(p) for p in STATE["plays"] if p["user_id"] == uid and p["biz_date"] == date],
                key=lambda r: r["entry_no"])
            return

        if "FROM cg_ferris_picks p" in s:          # history_for
            uid, limit = a
            out = []
            for (u, d), pk in STATE["picks"].items():
                if u != uid:
                    continue
                prize = next((p["prize"] for p in STATE["plays"]
                              if p["user_id"] == u and p["biz_date"] == d), None)
                out.append({"biz_date": d, "cabin": pk["cabin"], "tier": pk["tier"],
                            "prize": prize})
            self._rows = sorted(out, key=lambda r: r["biz_date"], reverse=True)[:limit]
            return

        if "FROM cg_ferris_picks WHERE user_id" in s:   # pick_for
            pk = STATE["picks"].get((a[0], a[1]))
            self._rows = [dict(pk)] if pk else []
            return

        if "INSERT INTO cg_ferris_picks" in s:
            uid, date, code, cabin, tier, ts = a
            STATE["picks"].setdefault((uid, date), {"cabin": cabin, "tier": tier})
            return

        if "SELECT daily_cap FROM cg_settings" in s:
            cap = STATE["settings"].get(a[0])
            self._rows = [{"daily_cap": cap}] if cap is not None else []
            return

        if "INSERT INTO cg_settings" in s:
            STATE["settings"][a[0]] = int(a[1])
            return

        if "SUM(prize)" in s and "cg_plays" in s:
            self._rows = [{"used": sum(p["prize"] for p in STATE["plays"]
                                       if p["biz_date"] == a[0])}]
            return

        if "SELECT * FROM cg_sessions WHERE code" in s:
            sess = STATE["sessions"].get(a[0])
            self._rows = [dict(sess)] if sess else []
            return

        if "SELECT code FROM cg_sessions WHERE user_id" in s:
            uid, date = a
            hit = [v for v in STATE["sessions"].values()
                   if v["user_id"] == uid and v["biz_date"] == date]
            hit.sort(key=lambda r: r["created_at"], reverse=True)
            self._rows = [{"code": hit[0]["code"]}] if hit else []
            return

        if "INSERT INTO cg_sessions" in s:
            code, uid, acct, name, date, ts = a
            STATE["sessions"][code] = {"code": code, "user_id": uid, "account": acct,
                                       "name": name, "biz_date": date, "created_at": ts}
            return

        if "INSERT INTO cg_plays" in s:
            code, uid, acct, date, entry_no, step, prize, tier, ts = a
            # stands in for UNIQUE (user_id, biz_date, entry_no)
            if any(p["user_id"] == uid and p["biz_date"] == date and p["entry_no"] == entry_no
                   for p in STATE["plays"]):
                raise IntegrityError("duplicate key value violates unique constraint")
            STATE["plays"].append({"code": code, "user_id": uid, "account": acct,
                                   "biz_date": date, "entry_no": entry_no, "step": step,
                                   "prize": prize, "tier": tier, "played_at": ts})
            return

        raise AssertionError("fakedb has no handler for: " + s[:140])

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _Conn:
    def __init__(self):
        self.autocommit = True

    def cursor(self, cursor_factory=None):
        return _Cur()

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def connect(*a, **k):
    return _Conn()


class extras:
    RealDictCursor = object

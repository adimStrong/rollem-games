# -*- coding: utf-8 -*-
"""Statistical + structural tests for the race draw. No database and no browser needed.

draw_outcome() is the only place real money is decided in this game, so it is tested on its own: the
house rule (a real player can never place 1st or 2nd), the per-player odds, and the exact shape the dev
page replays. Run it before any deploy that touches the draw.

usage: python tests/test_draw.py [trials]
"""
import importlib.util
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# app.py reads DATABASE_URL and calls init_db() at import, so the module is loaded with the DB calls
# stubbed out -- the draw itself touches nothing.
os.environ.setdefault("DATABASE_URL", "postgresql://stub/stub")
os.environ.setdefault("ADMIN_PASSWORD", "stub")
os.environ.setdefault("SECRET_KEY", "stub")

import psycopg2  # noqa: E402

psycopg2.connect = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no DB in this test"))
spec = importlib.util.spec_from_file_location("gbr_app", os.path.join(ROOT, "app.py"))
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
except RuntimeError:
    pass  # init_db() is expected to fail; everything above it is loaded

draw_outcome = mod.draw_outcome
PRIZES, FIELD, P3, MAX_ENTRIES = mod.PRIZES, mod.FIELD, mod.P3, mod.MAX_ENTRIES

TRIALS = int(sys.argv[1]) if len(sys.argv) > 1 else 40000
fails = 0


def ok(cond, msg, extra=""):
    global fails
    print(("PASS " if cond else "FAIL ") + msg + (("  -- " + str(extra)[:200]) if (extra and not cond) else ""))
    if not cond:
        fails += 1


rng = random.Random(12345)

print("PRIZES by place:", PRIZES, " field:", FIELD, " P3:", P3, " max real entries:", MAX_ENTRIES)
print()

# ---- 1. structure, across every legal roster size ----
for n_real in range(2, MAX_ENTRIES + 1):
    bad_shape = bad_perm = bad_times = bad_crash = 0
    for _ in range(400):
        o = draw_outcome(n_real, FIELD, rng)
        if set(o) != {"seed", "order", "times", "surge", "crashes"}:
            bad_shape += 1
        if sorted(o["order"]) != list(range(FIELD)) or len(o["times"]) != FIELD:
            bad_perm += 1
        if o["times"] != sorted(o["times"]) or o["times"][0] != 15.0:
            bad_times += 1
        last_real = max(q for q, ri in enumerate(o["order"]) if ri < n_real)
        for c in o["crashes"]:
            # a crash must never be able to move a real player's place
            if c["idx"] < n_real or o["order"].index(c["idx"]) <= last_real:
                bad_crash += 1
        if not (1 <= o["seed"] < 2 ** 31 - 1):
            bad_shape += 1
    ok(bad_shape == 0, "%d players: outcome has exactly the keys the page replays" % n_real, bad_shape)
    ok(bad_perm == 0, "%d players: order is a permutation of all %d lanes, times has one per lane" % (n_real, FIELD), bad_perm)
    ok(bad_times == 0, "%d players: times ascend from 15.0s (winner first)" % n_real, bad_times)
    ok(bad_crash == 0, "%d players: only fillers behind every real player can crash" % n_real, bad_crash)

print()
# ---- 2. the house rule and the odds ----
for n_real in (1, 2, 3, 4, 5):
    if n_real > MAX_ENTRIES:
        continue
    first_second = 0
    places = {}
    prize_total = 0.0
    for _ in range(TRIALS):
        o = draw_outcome(n_real, FIELD, rng)
        for ri in range(n_real):
            p = o["order"].index(ri) + 1
            places[p] = places.get(p, 0) + 1
            if p <= 2:
                first_second += 1
            prize_total += PRIZES[p - 1]
    entries = TRIALS * n_real
    ok(first_second == 0, "%d players: a real player NEVER finishes 1st or 2nd (P%d / P%d are display-only)"
       % (n_real, PRIZES[0], PRIZES[1]), first_second)
    p3 = places.get(3, 0) / entries
    ok(abs(p3 - P3) < 0.006, "%d players: 3rd place lands %.3f%% of entries (want %.1f%%)"
       % (n_real, p3 * 100, P3 * 100), p3)
    ev = prize_total / entries
    want_ev = P3 * PRIZES[2] + (1 - P3) * PRIZES[3]
    ok(abs(ev - want_ev) < 0.06, "%d players: expected cost per entry %s (want %s)"
       % (n_real, round(ev, 3), round(want_ev, 3)), ev)
    paid = sorted({PRIZES[p - 1] for p in places})
    ok(paid == sorted(set(PRIZES[2:])), "%d players: only the 3rd-and-below amounts are ever paid" % n_real, paid)

print()
# ---- 3. the seed makes the race reproducible for every viewer ----
a = draw_outcome(4, FIELD, random.Random(7))
b = draw_outcome(4, FIELD, random.Random(7))
# a roster that would leave fewer than 3 spare lanes must be refused, not silently mis-drawn
try:
    draw_outcome(FIELD - 2, FIELD, rng)
    ok(False, "a roster with only 2 spare lanes is refused")
except AssertionError:
    ok(True, "a roster with only 2 spare lanes is refused instead of mis-drawing 3rd place")
ok(MAX_ENTRIES == FIELD - 3, "MAX_ENTRIES leaves exactly 3 spare lanes", MAX_ENTRIES)

ok(a == b, "the same RNG state produces an identical outcome (so every viewer replays one race)")
ok(draw_outcome(4, FIELD, random.Random(7)) != draw_outcome(4, FIELD, random.Random(8)),
   "a different RNG state produces a different outcome")

print("\n%s  (%d failure(s), %d trials per size)" % ("ALL PASS" if not fails else "FAILURES", fails, TRIALS))
sys.exit(1 if fails else 0)

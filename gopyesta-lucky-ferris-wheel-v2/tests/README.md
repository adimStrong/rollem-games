# Local test recipe (no production DB needed)

```
docker run -d --name lfw2-test -e POSTGRES_PASSWORD=cgtest -e POSTGRES_DB=cg -p 55432:5432 postgres:16-alpine
python tests/fixture.py                      # gpr-shaped users/deposits/bets_daily_category + today's sample rows
python tests/ledger_stub.py &                 # fake wins-ledger on :8799 -> tests/ledger_posts.jsonl
DATABASE_URL=postgresql://postgres:cgtest@localhost:55432/cg ADMIN_PASSWORD=testpw SECRET_KEY=x \
  LEDGER_URL=http://127.0.0.1:8799/api/win PORT=8798 python app.py &
PYTHONIOENCODING=utf-8 python tests/test_ui.py   # Playwright: demo play-through + real admin link -> player spin (run FIRST, uses uitest1)
PYTHONIOENCODING=utf-8 python tests/test_api.py  # eligibility/odds/cap/second-spin-refused/ledger assertions (uses juan123/maria_x/pedro)
```
Re-run `fixture.py` (and restart `app.py` — it recreates the `fw_spins`/`cg_*` tables, which stay
compatible across restarts since they're `CREATE TABLE IF NOT EXISTS`) between full runs. Stop the
docker container with `docker rm -f lfw2-test` when done.

Accounts seeded by `fixture.py`:
- `juan123` — deposit ₱250 @13:30 (window), turnover ₱900 egame + ₱400 casino = ₱1300 >= 3×250=750 -> ELIGIBLE
- `maria_x` — deposit ₱150 @14:00 (window), turnover ₱200 egame = ₱200 < 3×150=450 -> turnover-locked
- `tester` — is_test=1, excluded from lookup entirely
- `pedro` — deposit ₱1000 @16:00, turnover ₱5000 egame -> eligible, used to drive the daily-cap test
  (cg_settings seeded with a near-exhausted cap for today)
- a deposit outside the 1PM-9PM window and a `Failed`-status deposit are seeded too, to prove the
  window/status filters still work.

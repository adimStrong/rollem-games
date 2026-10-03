# Local test recipe (no production DB needed)

```
docker run -d --name cg-test -e POSTGRES_PASSWORD=cgtest -e POSTGRES_DB=cg -p 55432:5432 postgres:16-alpine
python tests/fixture.py                      # gpr-shaped users/deposits/bets_daily_category + today's sample rows
python tests/ledger_stub.py &                # fake wins-ledger on :8799 -> tests/ledger_posts.jsonl
DATABASE_URL=postgresql://postgres:cgtest@localhost:55432/cg ADMIN_PASSWORD=testpw SECRET_KEY=x \
  LEDGER_URL=http://127.0.0.1:8799/api/win PORT=8798 python app.py &
PYTHONIOENCODING=utf-8 python tests/test_ui.py   # Playwright: admin lookup -> link -> 2 plays (uses 2 of 4 entries)
PYTHONIOENCODING=utf-8 python tests/test_api.py  # entries/window/wagering/cap/ledger assertions
```
Re-run `fixture.py` (and restart app.py — it recreates the cg_ tables) between full runs.

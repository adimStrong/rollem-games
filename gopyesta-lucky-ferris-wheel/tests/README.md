# Local test recipe (no production DB needed)

```
docker run -d --name fw-test -e POSTGRES_PASSWORD=cgtest -e POSTGRES_DB=cg -p 55432:5432 postgres:16-alpine
python tests/fixture.py                      # gpr-shaped users/deposits/bets_daily_category + today's sample rows
python tests/ledger_stub.py &                # fake wins-ledger on :8799 -> tests/ledger_posts.jsonl
DATABASE_URL=postgresql://postgres:cgtest@localhost:55432/cg ADMIN_PASSWORD=testpw SECRET_KEY=x \
  LEDGER_URL=http://127.0.0.1:8799/api/win PORT=8798 python app.py &
PYTHONIOENCODING=utf-8 python tests/test_api.py  # 47 checks: deposit/slot counting, pick, spin, turnover, cap, ledger
PYTHONIOENCODING=utf-8 python tests/test_ui.py   # Playwright (reduced motion): player link -> pick cabin -> auto spin -> popup; admin lookup -> link
```
Re-run `fixture.py` (and restart app.py — it recreates the `fw_spins` table) between full runs. `test_ui.py` expects a fresh seed too.

Fixture players: `Juan123` (deposit 400, slots 900 → tier 1/2 goals met), `maria_x` (deposit 80 → short), `pedro` (cap test),
`luis` (casino 9,000 but no slots → must NOT count), `tester` (is_test=1 → not found).

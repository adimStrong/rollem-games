# Local test recipe (no production DB needed)

POTS Pearl Mine (PLATFORM=pots):
```
docker run -d --name cg-pots-test -e POSTGRES_PASSWORD=cgtest -e POSTGRES_DB=cg -p 55441:5432 postgres:16-alpine
python tests/fixture_pots.py
python tests/ledger_stub.py 8791 &
DATABASE_URL=postgresql://postgres:cgtest@localhost:55441/cg ADMIN_PASSWORD=testpw SECRET_KEY=x PLATFORM=pots \
  LEDGER_URL=http://127.0.0.1:8791/api/win PORT=8841 python app.py &
PYTHONIOENCODING=utf-8 python tests/test_api.py pots http://127.0.0.1:8841
PYTHONIOENCODING=utf-8 python tests/test_ui.py http://127.0.0.1:8841
```
Tamasa Swerte Lights (PLATFORM=tms) — same, with `fixture_tms.py`, port 55442 / app 8842 / ledger 8792 and
`PLATFORM=tms BRAND=tamasa BRAND_LABEL=TamasaPH GAME_NAME="Swerte Lights" PER_PLAY=200 DAILY_CAP=15000 DEP_FROM=13:00
PRIZES='[[8.2,90],[16.5,10]]' WILD_RATE=0.05 WILD_PRIZES='[[8.2,95],[16.5,5],[777,0]]'`.

Re-run the fixture (and restart app.py) between full runs. `docker rm -f cg-pots-test` when done.
On Windows, set env vars with `$env:NAME="..."` in PowerShell before `python app.py`.

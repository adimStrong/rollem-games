# Apply the Gopyesta → Lucky Ferris Wheel swap (rollem-games)

The agent could not write into `C:\Users\us\Projects\rollem-games` (auto-mode classifier: "Modify Shared Resources"),
so the finished, tested package sits at `C:\tmp\gopyesta-lucky-ferris-wheel\` and the wins-ledger patch at
`C:\tmp\wins-ledger-patch\`. Run the steps below in PowerShell.

## 0. One-time preamble (git is not on PATH in plain PowerShell)
```powershell
$env:PATH += ";C:\Users\us\AppData\Local\Programs\Git\cmd"
```

## 1. Main repo: add the new game folder (old `gopyesta-palarong-pyesta/` stays for history) + ledger amount patch
```powershell
cd C:\Users\us\Projects\rollem-games
Copy-Item -Recurse -Force C:\tmp\gopyesta-lucky-ferris-wheel .\gopyesta-lucky-ferris-wheel
Remove-Item -Recurse -Force .\gopyesta-lucky-ferris-wheel\tests\ledger_posts.jsonl -ErrorAction SilentlyContinue
Copy-Item -Force C:\tmp\wins-ledger-patch\app.py .\_wins-ledger\app.py
git add gopyesta-lucky-ferris-wheel _wins-ledger/app.py
git commit -m "gopyesta: swap Palarong Pyesta for Lucky Ferris Wheel (cabin pick, deposit+slot goal, server-rolled P8-888 bonus, 5x turnover); wins-ledger accepts any gopyesta amount 1-1000"
git push origin main
```

## 2. wins-ledger service (deploy FIRST so the new amounts are accepted)
```powershell
cd C:\Users\us\Projects\rollem-games-branches\wins-ledger
Copy-Item -Force C:\tmp\wins-ledger-patch\app.py .\app.py
git add app.py; git commit -m "Accept Lucky Ferris Wheel amounts (gopyesta 1-1000)"; git push
Get-Location; railway status          # must say Project rollem-games / Service wins-ledger
railway up --service wins-ledger --detach
```

## 3. gopyesta service (same service, same URL gopyesta-production.up.railway.app)
```powershell
cd C:\Users\us\Projects\rollem-games-branches\gopyesta
Copy-Item -Force C:\tmp\gopyesta-lucky-ferris-wheel\app.py .\app.py
Copy-Item -Force C:\tmp\gopyesta-lucky-ferris-wheel\Procfile .\Procfile
Copy-Item -Force C:\tmp\gopyesta-lucky-ferris-wheel\requirements.txt .\requirements.txt
Remove-Item -Recurse -Force .\static; Copy-Item -Recurse -Force C:\tmp\gopyesta-lucky-ferris-wheel\static .\static
git add -A; git commit -m "Lucky Ferris Wheel replaces Palarong Pyesta"; git push
Get-Location; Get-ChildItem static\index.html; railway status   # must say Service: gopyesta  (see the gspot wrong-dir gotcha)
railway up --service gopyesta --detach
```
No Railway variable changes are needed: it keeps `DATABASE_URL` (gpr Postgres public URL), `ADMIN_PASSWORD`, `SECRET_KEY`, `TZ`.
Optional tuning vars (all have defaults): `WHEEL_TIERS` (JSON `[[bet,min,max],…]`), `MIN_DEPOSIT=100`, `TURNOVER_MULT=5`,
`WAGER_CATS=egame`, `DAILY_CAP=10000`, `ROUNDS_PER_DAY=1`, `DEP_FROM=00:00`, `DEP_TO=24:00`, `PLAY_UNTIL=23:59`.

## 4. Verify (about 40 s after each deploy)
```powershell
Invoke-RestMethod https://wins-ledger-production.up.railway.app/health
Invoke-RestMethod https://gopyesta-production.up.railway.app/health        # {"ok":true,"game":"Lucky Ferris Wheel",...}
Invoke-RestMethod https://gopyesta-production.up.railway.app/api/config    # tiers, cabTier, minDeposit 100, wagerCats ["egame"]
```
Then open https://gopyesta-production.up.railway.app/#admin → password → Check a real username → "Gumawa ng link".
The player opens the link, picks a cabin, and the wheel spins by itself once the day's deposit (≥₱100) and slot bets reach the cabin target.
The `fw_spins` table is created on first boot in the gpr database; `cg_sessions`/`cg_settings` are reused. Old Palarong links keep resolving to the account's session but show the wheel.

## What changed vs. Palarong Pyesta (same harness, new mechanic)
- Entry model → cabin model: `POST /api/pick/<code> {cabin}`, `POST /api/spin/<code>`, `POST /api/seen/<code>`; `GET /api/session/<code>` now returns `cur`, `dep`, `slot`, `other`, `depOk`, `betOk`, `ready`, `missing`, `wager`, `hist`, `week`.
- Deposit = total Success deposits for the day (whole day by default, not 1–9 PM); slot bets = `bets_daily_category` category `egame` only (casino no longer counts).
- Reward = random in the cabin tier's range (8–18 / 18–28 / 18–188 / 288–888), posted to wins-ledger with `game: "Lucky Ferris Wheel"`.
- Daily budget, admin link maker, T&C gate, manual GCash payout via wins-ledger: unchanged.
- Tests: `tests/README.md` (docker postgres + fixture + stub ledger; `test_api.py` 47 checks, `test_ui.py` Playwright 15 checks) — all passing on 2026-10-12.

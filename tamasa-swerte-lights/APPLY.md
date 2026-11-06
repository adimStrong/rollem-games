# Tamasa Swerte Lights — go-live steps (2026-11-07)

What it is: the `tamasa` service (tamasa-production.up.railway.app) swaps from the Triple Tama coin-toss (own Postgres-MEz7)
to the backend-verified **Swerte Lights** — the same cg3 "plays" backend as POTS Pearl Mine, pointed at the **tamasa-retention
Postgres** (Railway project tamasa-retention / service tms-postgres, the DB the TAMASA Sync Loop fills from the TMS console):
the admin looks the player up by username / user id, deposits (Success = console Approved, 1 PM–9 PM) and turnover are read
from that DB, every ₱200 deposit = 1 play (max 5/day), play k unlocks at 1× cumulative turnover (**all games count** — the TMS
console has no slot/casino split), prize drawn server-side (₱8.20 90% / ₱16.50 10%; 5% WILD rounds; 777 / 77 / BAR BAR
display-only), ₱15,000 shared daily budget, STOP ALL switch, wins posted to the wins-ledger (now accepts centavo amounts),
`/report` + no-password `/report/<token>` mirror.

STATUS 2026-11-07 ~01:30 PHT: code done and tested locally (tests/test_api.py 61/61, tests/test_ui.py 39/39), commits ready
in the three worktrees; nothing pushed/deployed yet (the Railway variable write and the pushes need JD — classifier-blocked).

## 1. Railway variables on the `tamasa` service (no deploy yet)
```
powershell -ExecutionPolicy Bypass -File C:\tmp\tamasa_swerte_lights_deploy\set_tamasa_vars.ps1
```
Reads the Tamasa DB DSN from `C:\tmp\tms_pg_dsn.txt` (replaces the Postgres-MEz7 reference), generates SECRET_KEY +
REPORT_SHARE_TOKEN (token saved to `C:\tmp\tamasa_swerte_lights_report_token.txt`), sets ADMIN_PASSWORD (project password),
PLATFORM=tms / BRAND=tamasa / GAME_NAME and the mechanic knobs — with `--skip-deploys`.

## 2. Deploy (push the branches → Railway autodeploy) — wins-ledger FIRST
```
$env:PATH += ";C:\Users\us\AppData\Local\Programs\Git\cmd"
cd C:\Users\us\Projects\rollem-games-branches\wins-ledger
git fetch origin; git log --oneline HEAD..origin/wins-ledger     # must print nothing
git push origin wins-ledger
cd C:\Users\us\Projects\rollem-games-branches\tamasa
git fetch origin; git log --oneline HEAD..origin/tamasa          # must print nothing
git push origin tamasa
cd C:\Users\us\Projects\rollem-games; git push origin main
```
Verify: `https://tamasa-production.up.railway.app/health` → `"game":"Swerte Lights"`, `/api/config` → `"version":"cg3"`,
`/#admin` → link maker + demo preview. wins-ledger boot widens `wins.amount` to DOUBLE PRECISION (one-off ALTER).

## 3. Per-link turnover refresh = inside the TAMASA Sync Loop (restart it once)
`C:\Users\us\Tamasa\tamasa-retention\link_turnover.py` runs INSIDE `tms_sync_loop.py` (same Chrome, same pacing): every 3 min
while the game is open (13:00–21:00), for every player with a link today, one member-report call filtered by username →
REPLACE-upserts `bets_daily_category` (category `all`) + `bets_daily` (ALL) for today. The running loop must be restarted
to load the new code:
```
powershell -ExecutionPolicy Bypass -File C:\tmp\tamasa_swerte_lights_deploy\restart_tms_loop.ps1
```
(stops the running `tms_sync_loop.py`, clears `sync_loop.lock`, re-runs the "TAMASA Sync Loop" task). Log: `logs\sync_loop.log`
— look for `[link] skipped: no linked players today` after the first cycle.

## Local test recipe
See `tests/README.md` (docker postgres 55442 + fixture_tms.py + ledger_stub.py 8792 + app on 8842; set PLAY_FROM=00:00
PLAY_UNTIL=23:59 when testing outside 1–9 PM).

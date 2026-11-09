# POTS Pearl Mine — go-live steps (2026-11-06)

What it is: the `pots` service (pots-production-f9dd.up.railway.app) swaps from the static Pearl Drop to the
backend-verified **Pearl Mine** (same architecture as GoPyesta's Lucky Ferris Wheel v2): the admin looks the
player up in the POTS888 database (pots-retention Postgres), deposits + slot turnover are read live, every
₱150 Success deposit (12 PM–9 PM) = 1 play, play k unlocks at 1× cumulative slot turnover, max 5 plays/day,
prize drawn server-side (₱7 90% / ₱17 10%; ₱27/₱57/₱77 display-only), ₱10,000 shared daily budget,
STOP ALL switch, wins posted to the wins-ledger, `/report` + no-password `/report/<token>` mirror.

STATUS 2026-11-06 ~20:10 PHT: steps 1 and 2 are DONE (vars set with skip-deploys; wins-ledger 2c9fb09, pots 66f3895
and main 73b7e88 pushed → Railway autodeploy). Only step 3 (the Task Scheduler registration) was still refused by
the auto-mode classifier — run it yourself:

## 1. Railway variables on the `pots` service (no deploy yet)
```
C:\tmp\pots_pearl_mine_deploy\set_pots_vars.cmd
```
Reads the POTS DB DSN from `C:\tmp\pots_pg.txt`, generates SECRET_KEY + REPORT_SHARE_TOKEN (token saved to
`C:\tmp\pots_pearl_mine_report_token.txt`), sets ADMIN_PASSWORD (project password), PLATFORM/BRAND/GAME_NAME and
the mechanic knobs — with `--skip-deploys`. Needs `railway` on PATH (`C:\Users\us\AppData\Roaming\npm`) and the
CLI logged in to the account that owns rollem-games.

## 2. Deploy (push the `pots` branch → Railway autodeploy)
The worktree `C:\Users\us\Projects\rollem-games-branches\pots` holds the new files once step "swap" below ran.
If the push was blocked for me, run (PowerShell):
```
$env:PATH += ";C:\Users\us\AppData\Local\Programs\Git\cmd"
cd C:\Users\us\Projects\rollem-games-branches\pots
git fetch origin; git log --oneline HEAD..origin/pots     # must print nothing (no foreign commits)
git push origin pots
```
Verify: `https://pots-production-f9dd.up.railway.app/health` → `"game":"Pearl Mine"`, `/api/config` → `"version":"cg3"`.
wins-ledger must be deployed FIRST (branch `wins-ledger`, same push flow) — it now accepts ₱7 for brand `pots`.

## 3. Per-link turnover sync on this PC (Task Scheduler, every 5 min, 9-min limit)
```
powershell -ExecutionPolicy Bypass -File C:\tmp\pots_pearl_mine_deploy\register_link_sync_task.ps1
```
Registers "POTS Pearl Mine Link Turnover 5m" → `run_pm_link_sync.bat` → `pots_link_turnover_sync.py --once`
(in `C:\Users\us\Pots\pots-retention`). Each cycle, inside 12:00–21:00, for every player with a link today it
makes ONE admin call (`bet_log_v3s/summary?user_id=…`) and REPLACE-upserts `bets_daily_category` (per category,
full-day totals — pre-link bets included). Shares the admin session file with POTS Live Sync (same PC only).
Log: `logs\pm_link_sync.log`. Verified 2026-11-06 19:39 against the live admin into a throwaway DB.

## Dev build 2026-11-09 (ported from the dev's `pots-pearl-mine.html`)
The dev's file was the OLD standalone prototype (localStorage links, no `/api/*`, Claude-artifact admin gate), so it was
NOT swapped in. Only its visual/game-feel changes were ported onto this server-driven page: 4×4 clam bed (16 clams,
5 urchins; ₱17 = 5–7 pearls), 4-rung ladder (₱7 · ₱17 · ₱27 · ₱57 — no ₱777 rung), THREE ₱777 decoy pearls (black
pearl + gold chip, display only) in every final reveal, "clean look" (no sun rays, caustics, kelp, marine snow,
bubbles, fish, sparks, confetti), steady camera (no parallax/drift/shake, no gyro), flat sand, 512 shadow map,
lower DPR (1.2 phone / 1.5 desktop). Engine, admin, T&C process copy and the fit()-before-open resume fix are unchanged.
Old 25-tile plans from before the deploy fail `validPlan` and show as finished boards (amounts are the server's anyway).
Verified: test_api 62/62, test_ui 31/32 (the 1 "fail" was stale ledger-stub rows from the previous run), demo check 3×₱777.

## Local test recipe
See `tests/README.md` (docker postgres + fixture_pots.py + ledger_stub.py; `tests/test_api.py` = 62 checks,
`tests/test_ui.py` = Playwright play-through).

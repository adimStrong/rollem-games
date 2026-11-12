# Games Tracker — all sites, all community games, one conversion view

One Flask service (`games-tracker` on Railway, branch `games-tracker`) that reads every game's own
database and the shared wins-ledger, and shows per site and per day:

    links made → players linked → players who played → players who won → ₱ paid

- **cg3 games** (POTS, Tamasa, Win For Life, Roll'em) and **fw2** (GoPyesta): `cg_sessions` = links,
  `cg_plays` (status `paid`) = plays / prizes / seen. Qualifying deposit = the per-player `dep`
  behind the day's plays (cg3 only).
- **Static, agent-verified games** (GameSpot, Time2Bet): only wins reach the ledger, one per play,
  so links are "not tracked" and played = winners.
- Daily cap and the live game name come from each game's public `/api/config`.

Env: `DSN_<BRAND>` per DB game, `DSN_LEDGER` (internal URL works inside the project) or
`LEDGER_REPORT_<BRAND>` public report URLs as a fallback, optional `REPORT_URLS` JSON for the
"Report" links, `CACHE_TTL` (60 s), `SINCE` (2026-09-01). Aggregates only — no player names.

Local run: `python app.py` with the env set (see the deploy script in C:\tmp); `/api/data` for the JSON.

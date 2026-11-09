# Community game backend v3 ("plays" model) — API contract

Shared by `pots-pearl-mine/` (PLATFORM=pots) and `tamasa-swerte-lights/` (PLATFORM=tms). Same shape as the
gopyesta Lucky Ferris Wheel v2 backend, minus the cabin pick: a play is created **and paid in one call**.

## Link modes (frontend)
`#admin` = link maker (password-gated) · `#<code>` where code matches `^[a-z0-9]{1,32}-[a-z0-9]{2,8}$` = a player
session for one account/day · anything else = DEMO (local random draw, nothing recorded).

## Player endpoints (no auth)
- `GET /api/config` → `{brand, brandLabel, game, platform, version:"cg3", prizes:[{amt,p}], wildRate, wildPrizes:[{amt,p}],
  perPlay, maxPlays, turnover, wagerCats, dailyCap, depFrom, depTo, playFrom, playUntil, maxPrize, minPrize}`
- `GET /api/session/<code>` → `{exists:false}` or
  `{exists:true, code, name, account, expired, config, dep, slot, other, syncedAt, plays:[PLAY], playsUsed, playsTotal,
  playsLeft, nextNeed, depOk, betOk, ready, missing:[string], wager:{bonus,need,done,cleared}, hist:[PLAY], week,
  capLeft, capped, windowOpen, playOpen, serverTime, stopped, stopNote}`
  - `playsTotal` = min(floor(dep / perPlay), maxPlays); `playsUsed` = plays already paid today
  - `nextNeed` = perPlay × turnover × (playsUsed+1) — cumulative slot turnover needed for the NEXT play
  - `ready` = depOk && betOk && playOpen && !stopped && !capped  (START may be pressed)
  - `missing` = Taglish reasons when not ready (e.g. "mag-deposit pa ng ₱150", "mag-slots pa ng ₱120")
- `POST /api/play/<code>` → `200 {ok:true, played:true, play:PLAY, ...session state}`
  or `409 {error: "stopped"|"closed"|"done"|"no_new_deposit"|"locked"|"cap"|"expired"|"race", msg, ...state}`,
  `404 {error:"no_session"}`. The server draws the prize (`play.amount` pesos, `play.tier`, `play.wild`).
- `POST /api/plan/<code>` `{id, plan:{...}}` → `{ok}` — store the COSMETIC reveal plan for that play (≤6 KB JSON:
  pearl values/clam order/taps, or the light-board cell / wild layout) so a refresh replays the same board.
  Overwrites; call again after every tap. Never changes the amount.
- `POST /api/seen/<code>` `{id}` → `{ok}` — after the player closes the win card. A paid play with `seen:0` on load
  must be animated again (same as the wheel).

`PLAY = {id, day, play_no, amount, tier, wild, plan|null, status:"paid", seen:0|1, need, dep, slot, at, cleared}`
`amount` is pesos (number; may be decimal e.g. 8.2 / 16.5). `tier` indexes `config.prizes` (or `config.wildPrizes` when wild).

## Admin endpoints (header `X-Admin-Token`)
- `POST /api/admin-login {password}` → `{token}` (403 on wrong password)
- `GET /api/lookup?account=<username|user id|game id>` → `{found:false, account, ...cap}` or `{found:true, code|null, ...summary}`
  summary adds: `account, name, gameId, date, deposits:[{amount,at}], linksIssued`
- `POST /api/link {account, fresh?}` → same as lookup with `code` set (reuses today's link unless `fresh`);
  `409 {error:"cap"|"stopped"}`, `404` unknown account
- `GET /api/cap` / `POST /api/cap {dailyCap}` → `{ok, date, defaultCap, dailyCap, capUsed, capLeft, capped, stopped, stopNote}`
- `GET /api/stop` / `POST /api/stop {stopped, note}` → `{ok, stopped, stopNote}`  (global kill switch)
- `GET /api/links-today?from=YYYY-MM-DD&to=YYYY-MM-DD` (also accepts `?token=<REPORT_SHARE_TOKEN>`) →
  `{from, to, players:[{user_id, account, name, gameId, links, rounds, won, depAmount, depCount, turnover, last_link_at, links_issued}]}`

## Pages
`/` index.html · `/report` (admin password) · `/report/<REPORT_SHARE_TOKEN>` (no password) · `/health`

## Env
`DATABASE_URL ADMIN_PASSWORD SECRET_KEY` required · `PLATFORM=pots|tms BRAND BRAND_LABEL GAME_NAME` ·
`PER_PLAY MAX_PLAYS TURNOVER_MULT WAGER_CATS DAILY_CAP DEP_FROM DEP_TO PLAY_FROM PLAY_UNTIL PRIZES WILD_RATE WILD_PRIZES` ·
`LEDGER_URL REPORT_SHARE_TOKEN TZ`

# Community Games — source

8 single-file HTML promo minigames, one per brand, each self-hosted on Railway as its own
service deployed from its own branch in this repo.

| Branch | Laro | Brand | Deploy kind |
| --- | --- | --- | --- |
| `gopyesta` | Lucky Ferris Wheel | Gopyesta | Flask + Postgres (platform-verified deposits + turnover) |
| `pots` | Pearl Drop | POTS | static |
| `rollem` | Roll It (3D dice) — `rollem-roll-it-v2/` | Roll'em | Flask + Postgres cg3 (platform-verified deposits + turnover from the rollem-retention DB) |
| `winforlife` | Spin For Life (roulette) — `wfl-spin-for-life-v2/` | Win For Life | Flask + Postgres cg3 (platform-verified deposits + turnover from the wfl-retention DB) |
| `cow` | Cash Cow | COW88 | static |
| `tamasa` | Triple Tama (slot) | Tamasa | Flask + Postgres (live admin↔player sync) |
| `gspot` | Power-Up Cards (was Treasure Spot / Gagamba Spot / Loot Drop) | GameSpot | static |
| `t2b` | Time 2 Race (6-horse race; was T2B Derby) — `time2bet-time2race/` | Time2Bet | static (agent-verified; different console vendor) |
| `gobetplay` | GoBet Race (3D carabao race) — `gobetplay-gobet-race/` | GoBetplay | Flask + Postgres (platform-verified from the gobetplay-retention DB) |

`dice-roll-tester/` and `raffle-wheel/` are not deployed as community games (internal tool /
no dedicated brand).

**GoBet Race is the one game that is not one-player-per-link.** It is a shared live event: an agent adds
up to 5 qualified players to the open lobby and presses Start, and every page on the same URL replays one
server-drawn outcome (`GET /api/race`, polled once a second). The field is always 8 lanes and the empty
ones are filled with plausible usernames, because **1st (₱177) and 2nd (₱77) always go to those fillers** —
a real player can only place 3rd (₱27, 5%) or lower (₱7), i.e. the same ₱8.00 expected cost per entry as
the other brands. There is no link token, so nothing to expire; entries are keyed to the day instead.

## Mechanic (all 8 games, same rules)

- Minimum qualifying deposit: **₱200**. On the five STATIC brands an agent verifies it
  off-platform and types the amount. On **`gopyesta`, `rollem` and `tamasa` it is read
  from the platform database** — the agent only types a username, and on `gopyesta` an
  entry stays locked until real slots+casino turnover reaches 3x the deposits behind it.
- Prize pool is flat: **₱10 (4%), ₱27 (95%), ₱57 (1%)**. Marketing headline: "prizes up to ₱777"
  (a cap/tagline, not a literal 4th outcome).
- Admin flow: open `#admin`, enter the **player's name**, the page generates a unique link for
  that player. One play per link — a player can't reset and re-roll after seeing their result.

`gopyesta` keeps its source in `gopyesta-palarong-pyesta/` (folder name unchanged so the
Railway root directory keeps resolving). The branch is flattened to the repo root, as with
every brand; changes have to be made in BOTH places — `main`'s folder is the record, the
branch is what deploys.

## Links inside each game

- Admin / link maker: `#admin`
- Player view: the link the admin generates (or `#demo` for a demo view)

## Admin access

Every admin panel is now gated by a password (previously it depended on `window.claude`, which
only worked inside a Claude Artifact and would have permanently locked admin mode out once
self-hosted). The static games check a password client-side (a deterrent, consistent with the
rest of this project's security model — see below); `rollem` and `tamasa` check it server-side
via the `ADMIN_PASSWORD` env var. **The actual password is not committed here** — it was shared
with the user out of band when this was set up. To rotate it:
- Static games: recompute `ADMIN_PASS_CHECK = h36(newPassword + SALT)` (the file's own hash
  helper) and replace the hardcoded constant.
- `rollem` / `tamasa`: just change the `ADMIN_PASSWORD` Railway env var, no code change needed.

## Known limitations (carried over from the original design, not new)

- The per-link token on the 6 static games (`code.deposit.nonce.check`) is a **soft deterrent**
  against casual URL editing, not real security — the salt is visible in page source, so a
  motivated player could forge their own token. The actual fraud control is that an agent
  manually verifies the deposit screenshot before crediting any bonus. This was already the
  accepted design before this rewrite; it hasn't changed.
- `rollem` and `tamasa` have real server-side admin auth (token-based), which is stronger than
  the other 6 — but player-facing reads (`GET /api/session/<code>`) are unauthenticated by
  design, same threat model as the static games' player links.

## Paalala bago i-host sa sariling site

Lahat ng 8 laro ay gumagana na nang standalone sa Railway (hindi na kailangan ng Claude). Para
sa totoong payout, ang agent pa rin ang nagve-verify ng deposit at nagre-record ng resulta — wala
pang automated backend na nagse-set ng tier/nagre-record ng payout.

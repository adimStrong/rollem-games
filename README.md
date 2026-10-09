# Community Games — source

8 single-file HTML promo minigames, one per brand, each self-hosted on Railway as its own
service deployed from its own branch in this repo.

| Branch | Laro | Brand | Deploy kind |
| --- | --- | --- | --- |
| `gopyesta` | Lucky Ferris Wheel | Gopyesta | Flask + Postgres (platform-verified deposits + turnover) |
| `pots` | Pearl Drop | POTS | static |
| `rollem` | ROLL IT (3D dice) | Roll'em | Flask + Postgres (live admin↔player sync) |
| `winforlife` | Tree of Life | Win For Life | static |
| `cow` | Cash Cow | COW88 | static |
| `tamasa` | Triple Tama (slot) | Tamasa | Flask + Postgres (live admin↔player sync) |
| `gspot` | Loot Drop | GameSpot | static |
| `t2b` | T2B Derby | Time2Bet | static |

`dice-roll-tester/` and `raffle-wheel/` are not deployed as community games (internal tool /
no dedicated brand).

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

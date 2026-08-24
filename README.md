# yoto-iconer

Give every track on a Yoto Make-Your-Own playlist a display icon that actually
matches the song.

A Yoto MYO card has one icon slot per chapter and per track. Choosing an icon per
song is a judgement call; everything around it — OAuth, searching ~5,500 icons,
uploading images, rewriting the card — is mechanical. This tool does all the
mechanical work and leaves you (or an LLM) with just the choosing.

Works two ways:

- **By hand** — search the catalog, pick icons, apply. No AI involved.
- **With Claude** — Claude reads one compact document and picks all of them at once.
  This is what the tool is shaped for, and it handles non-English playlists.

Runtime dependencies: **none**. Pure Python standard library (`urllib`, `sqlite3`,
`http.server`); `uv` just manages the environment.

---

## Contents

1. [Install](#install)
2. [Getting API access](#getting-api-access) ← start here
3. [Build the icon catalog](#build-the-icon-catalog)
4. [Usage without Claude](#usage-without-claude)
5. [Usage with Claude](#usage-with-claude)
6. [Non-English playlists](#non-english-playlists)
7. [Command reference](#command-reference)
8. [File formats](#file-formats)
9. [Safety and recovery](#safety-and-recovery)
10. [Where things are stored](#where-things-are-stored)
11. [Tests](#tests)
12. [Known API quirks](#known-api-quirks)

---

## Install

```bash
git clone <this repo> && cd yoto-iconer
uv sync
uv run yoto-iconer --help
```

Every command below is `uv run yoto-iconer ...` from the repo directory. To drop the
prefix, `uv tool install .` or activate `.venv`.

---

## Getting API access

Yoto has no shared API key. You register your **own** application once, get a client
id, and sign in through your browser. Takes about two minutes.

### 1. Create a public client

1. Open **<https://dashboard.yoto.dev/>** and sign in with the same account your
   Yoto app uses.
2. Create a new application.
3. Set the client type to **public**.
   *A public client holds no secret — a desktop CLI cannot keep one. Security comes
   from PKCE, not from a secret.*
4. Register this redirect URL, **exactly**, including the port and path:

   ```
   http://127.0.0.1:8787/callback
   ```

5. Enable these scopes:

   | Scope | Why it is needed |
   |---|---|
   | `user:content:manage` | write your MYO playlists |
   | `user:content:view` | **read** them — see the note below |
   | `user:icons:manage` | upload community icons into your library |
   | `offline_access` | stay signed in between runs |

   > **Do not skip `user:content:view`.** Yoto's docs say `user:content:manage`
   > includes it. The API does not agree: it checks the literal scope string, and
   > `GET /content/{cardId}` returns **403** without it.

6. Copy the **Client ID**.

Verification is not required for personal use, and the client id is not a secret —
it identifies your app, it does not authorise anything on its own.

### 2. Store it and sign in

```bash
uv run yoto-iconer setup --client-id <YOUR-CLIENT-ID>
uv run yoto-iconer login
```

`login` starts a one-shot local server on `127.0.0.1:8787`, opens Yoto's login page,
catches the redirect, and exchanges the code for tokens. If no browser opens, copy
the URL it prints. Use `--no-browser` on a headless box.

Confirm it worked:

```bash
uv run yoto-iconer status
```

`setup` with no arguments reprints all of the above at any time.

### Where your credentials live

| File | Mode | Contents |
|---|---|---|
| `~/.config/yoto-iconer/tokens.json` | `0600`, always | access token, **refresh token**, expiry, scopes |
| `~/.config/yoto-iconer/config.json` | your umask | client id only — not a secret |

The refresh token is the only real secret and never leaves that file — nothing is
hardcoded, nothing is committed, and later runs refresh the access token silently so
you only sign in once. Override locations with `YOTO_ICONER_HOME`; override the
client id with `YOTO_CLIENT_ID`.

To revoke: delete the application in the Yoto dashboard, then
`rm ~/.config/yoto-iconer/tokens.json`.

---

## Build the icon catalog

```bash
uv run yoto-iconer catalog sync          # official set + 3,000 popular community icons
uv run yoto-iconer catalog stats
```

Two sources feed one local SQLite catalog with a full-text index:

- **official** (~500 icons) — Yoto's own set. These already have media ids, so
  applying one is instant and uploads nothing.
- **community** (~22,700 available) — [yotoicons.com](https://www.yotoicons.com).
  Scraped politely: rate limited, cached on disk, resumable. A community icon must be
  uploaded into your own icon library before a card can use it; `apply` does this
  lazily, only for icons you actually choose, deduplicated by file hash so nothing
  uploads twice.

```bash
uv run yoto-iconer catalog sync --official            # first-party only
uv run yoto-iconer catalog sync --community --pages 400   # 25 icons per page
uv run yoto-iconer catalog sync --user                # your own uploaded icons
```

Planning also does a live yotoicons lookup for any track the local catalog answers
badly, so a smaller crawl is fine to start with.

---

## Usage without Claude

Perfectly usable by hand. Search, choose, apply.

```bash
# 1. Find the card
uv run yoto-iconer cards
#   6o6Xz  Songs 1

# 2. See what is on it now
uv run yoto-iconer show 6o6Xz
#   01   Wheels on the Bus     -
#   02   Dinosaur Stomp        -

# 3. Search for icons, one subject at a time
uv run yoto-iconer search "school bus" -n 5
#    22.1  yoto:#SG9tZS...   [off] School bus   ~ transport city school bus vehicle
#    14.4  yotoicons:311     [com] bus          ~ bus

uv run yoto-iconer search "dinosaur" -n 5 --live
#    25.1  yotoicons:10107   [com] Dinosaur     ~ dinosaur dino
```

`--live` also queries yotoicons.com right now, which is worth it when the local
catalog looks thin. `--source official` restricts to icons that need no upload.

```bash
# 4. Write your choices by hand
cat > decisions.json <<'JSON'
{"cardId": "6o6Xz", "assignments": [
  {"t": "01", "icon": "yoto:#SG9tZS...",   "why": "school bus"},
  {"t": "02", "icon": "yotoicons:10107",   "why": "dinosaur"}
]}
JSON

# 5. Preview, then apply
uv run yoto-iconer apply -d decisions.json --dry-run
uv run yoto-iconer apply -d decisions.json
```

No `-p plan.json` is needed here, because you referenced icons by their real ids
(`yoto:#...` / `yotoicons:...`) rather than by a plan's short ids.

To browse icons visually first, <https://www.yotoicons.com> is searchable in a
browser — note the number in the icon's URL and use it as `yotoicons:<number>`.

---

## Usage with Claude

The point of the tool. Claude reads **one** document for the whole playlist and
answers once, instead of running a search per track.

```bash
uv run yoto-iconer cards                              # get the cardId
uv run yoto-iconer plan <cardId> -n 5 -o plan.json    # Claude reads what this PRINTS
#   ... Claude writes decisions.json ...
uv run yoto-iconer apply -d decisions.json -p plan.json --dry-run
uv run yoto-iconer apply -d decisions.json -p plan.json
```

**Why it is cheap.** `plan` emits every candidate icon **once** in a shared pool keyed
by a two-character id (`i7`) instead of repeating 43-character media ids; each icon is
a `source|name|tags` string with no image data; and a chapter holding a single track
collapses to one slot, halving the rows on cards built from audio files. A real
96-track playlist measured **8.9k tokens** — read once, answered once.

Two rules that matter:

- **Read what `plan` prints, not `plan.json`.** The printed view is the same document
  minus the `keys` map that only `apply` consumes — 23-30% cheaper on real cards.
- **Don't search per track.** The plan already has the candidates. Use
  `search --live` only for the few tracks whose candidates are all wrong.

Two files in this repo teach Claude the loop automatically:

- `CLAUDE.md` — read whenever Claude works in this repo.
- A personal skill at `~/.claude/skills/yoto-playlist-icons/` — triggers on any
  request about Yoto icons, from any directory. Not part of this repo.

Anything that speaks JSON can drive it; `--json` (a **global** flag, before the
subcommand) makes every command machine-readable.

---

## Non-English playlists

Both icon catalogs are tagged in English. A Hebrew, Cyrillic or CJK title matches
nothing, so `plan` marks those slots `"needs": "q"` with no candidates rather than
returning nonsense. Supply translated queries and re-plan:

```bash
uv run yoto-iconer titles <cardId> --needs-query -o titles.json
# write queries.json: {"<slot>": "<english search terms>", ...}
uv run yoto-iconer plan <cardId> --queries queries.json -n 5 -o plan.json
```

Describe what the song is **about**, in concrete picturable nouns — `chocolate milk`,
`windmill`, `hansel gretel gingerbread`. Never pass artist names or transliterations;
no icon is tagged "Batel Tzabari". `--queries` also overrides English titles, useful
when a title is a metaphor.

---

## Command reference

| Command | What it does |
|---|---|
| `setup [--client-id ID]` | print the client setup steps, or store the id |
| `login [--no-browser]` | OAuth2 PKCE sign-in via loopback |
| `status` | client id, login state, catalog contents |
| `cards` | list your MYO cards with their ids |
| `catalog sync [--official\|--community\|--user] [--pages N]` | build the local catalog |
| `catalog stats` | what is in the catalog |
| `search QUERY [-n N] [--source S] [--live]` | rank icons for one query |
| `titles CARD [--needs-query] [--only-missing] [-o FILE]` | slot → title, for translating |
| `plan CARD [-n N] [-o FILE] [--queries F] [--only-missing] [--no-live] [--text] [--source S]` | the LLM's input |
| `show CARD` | current track → icon mapping |
| `apply [CARD] -d FILE [-p PLAN] [--dry-run]` | write icons back |

`--json` is a **global** flag and must come *before* the subcommand:
`yoto-iconer --json show <card>`, never `show <card> --json`.

`--text` renders a plan for humans instead of JSON.

---

## File formats

### decisions.json

```json
{
  "cardId": "6o6Xz",
  "assignments": [
    { "t": "01",    "icon": "i7",             "why": "school bus - Wheels on the Bus" },
    { "t": "02.03", "icon": "yotoicons:1346", "why": "dinosaur" },
    { "t": "02.04", "icon": "yoto:#WsZrlAbV", "why": "a media id you already know" }
  ]
}
```

- **`t`** — the slot id. `"01"` is a chapter, `"01.03"` a track within it. A chapter
  slot with exactly one track stamps **both**, so the icon shows while audio plays.
  On cards built from uploaded files the ids are opaque strings, not numbers.
- **`icon`** — a plan short id (requires `-p plan.json`), `yotoicons:<id>`, a catalog
  key like `official:<mediaId>`, or a raw `yoto:#<mediaId>`.
- **`why`** — ignored by the tool. It exists so the diff is reviewable.
- Omit a track to leave it untouched.

### plan.json

`icons` maps short ids to `source|name|tags`, where `off` = official Yoto,
`com` = yotoicons.com community, `usr` = your own uploads. `tracks[]` carries `t`
(slot), `title`, `q` (the query used), `c` (candidate short ids), `now` (current icon,
if any) and `needs: "q"` when a title must be translated first.

---

## Safety and recovery

Yoto has no partial-update endpoint — a card is saved by POSTing the whole content
object back. So `apply` round-trips the exact object it fetched and mutates only
`display.icon16x16`; every other field, known or unknown, is preserved.

- The pre-change card is written to `~/.config/yoto-iconer/backups/<cardId>-<ts>.json`
  before any write.
- `--dry-run` prints the per-track diff and exits without uploading or writing.
- A single unresolvable icon is reported and skipped, not fatal — fix the cause and
  rerun the same command. Applying is idempotent.

**Restoring a backup.** There is no `restore` subcommand yet; the backup is the exact
card object, so posting it back is enough:

```bash
uv run python -c "
import json, sys
from yoto_iconer import api, auth
card = json.load(open(sys.argv[1]))
api.update_card(auth.access_token(), card)
print('restored', card['cardId'])
" ~/.config/yoto-iconer/backups/6o6Xz-20260825-003110.json
```

---

## Where things are stored

```
~/.config/yoto-iconer/
  config.json      client id
  tokens.json      refresh + access token (0600)
  catalog.sqlite   icons, FTS5 index, upload dedupe cache
  cache/           scraped pages and PNGs
  backups/         pre-change card snapshots
```

Override the root with `YOTO_ICONER_HOME`, and the client id with `YOTO_CLIENT_ID`.

---

## Tests

```bash
uv run pytest
```

105 tests. No network, no account, no credentials: fixtures and monkeypatched
transports throughout, with `YOTO_ICONER_HOME` redirected to a temp directory.

---

## Known API quirks

Found by running against a real account; each contradicts or is missing from
yoto.dev, and each is handled in the code.

1. **`GET /content/{cardId}` 403s with only `user:content:manage`.** The docs say
   manage implies `user:content:view`; the API checks the literal scope string.
2. **Icon upload rejects `multipart/form-data`** with *"A binary image file is
   required"*. It wants the raw image bytes as the body with an `image/*` content
   type — the FormData snippet in the docs does not work, the complete example
   further down the same page does.
3. **`GET /content/mine` returns summaries without chapters**, so track counts are
   unavailable until you fetch each card.

**Caveat:** yotoicons.com is a community site with no official API, so the scraper is
unofficial and could break if its markup changes. The official set never depends on
it — `catalog sync --official` plus `plan --no-live --source official` is a fully
first-party fallback.

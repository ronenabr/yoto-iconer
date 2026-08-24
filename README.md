# yoto-iconer

Match the tracks of a Yoto MYO playlist to display icons, with an LLM doing the
judgement and a CLI doing everything else. No browser automation, no image data
in the model's context.

The loop is three commands:

```bash
uv run yoto-iconer plan <cardId> -o plan.json   # compact candidates for every track
#   ... the LLM reads plan.json and writes decisions.json ...
uv run yoto-iconer apply -d decisions.json -p plan.json --dry-run
uv run yoto-iconer apply -d decisions.json -p plan.json
```

## Why it is cheap to run

`plan` emits one JSON document for the whole playlist:

* every candidate icon appears **once**, in a shared `icons` pool, referenced by
  a two-character id (`i7`) rather than a 43-character mediaId;
* icon entries are `source|name|tags` strings, never image data;
* a chapter holding a single track collapses into one slot, so a 40-track MYO
  card built from audio files produces 40 rows, not 80.

A forty-track playlist lands around 2-4k tokens. The model reads it once and
answers once.

## Install

```bash
git clone <this repo> && cd yoto-iconer
uv sync
uv run yoto-iconer --help
```

Runtime dependencies: none. `uv` manages the environment; the package itself is
pure standard library (`urllib`, `sqlite3` with FTS5, `http.server`).

## Setting up API access

You need your own **public** OAuth client. It takes about two minutes:

1. Open <https://dashboard.yoto.dev/> and sign in with the same account your
   Yoto app uses.
2. Create an application, client type **public** (this tool holds no secret).
3. Register this redirect URL exactly:
   ```
   http://127.0.0.1:8787/callback
   ```
4. Enable these scopes:
   | Scope | Why |
   |---|---|
   | `user:content:manage` | write your MYO playlists |
   | `user:content:view` | read them (`manage` does not imply it at the API) |
   | `user:icons:manage` | upload community icons into your library |
   | `offline_access` | stay signed in between runs |
5. Store the client id and sign in:
   ```bash
   uv run yoto-iconer setup --client-id <YOUR-CLIENT-ID>
   uv run yoto-iconer login
   ```

`login` runs a one-shot local server on `127.0.0.1:8787`, opens Yoto's login
page, and stores a refresh token in `~/.config/yoto-iconer/tokens.json` (mode
0600). Later runs refresh silently. Verification is not required for personal
use.

`yoto-iconer setup` with no arguments reprints these steps.

## Building the icon catalog

```bash
uv run yoto-iconer catalog sync              # official set + 3000 popular community icons
uv run yoto-iconer catalog sync --official   # official set only
uv run yoto-iconer catalog sync --community --pages 400
uv run yoto-iconer catalog stats
```

Two sources feed one local SQLite catalog:

* **official** — Yoto's own icon set (`GET /media/displayIcons/user/yoto`).
  These already have mediaIds, so applying one costs nothing extra.
* **community** — [yotoicons.com](https://www.yotoicons.com), ~22,700 icons.
  Scraped politely (rate limited, cached on disk) because the site has no API.
  A community icon has to be uploaded into your own icon library before a card
  can reference it; `apply` does that lazily, only for icons you actually pick,
  deduplicated by file hash so nothing is uploaded twice.

Planning also does a live yotoicons tag lookup for any track the local catalog
answers badly, and folds the results into the catalog. Pass `--no-live` to keep
`plan` entirely offline.

## Non-English playlists

Both catalogs are tagged in English. `plan` marks any title that is not in the
Latin alphabet as `"needs": "q"` and skips searching it, rather than returning
nonsense. Supply translated queries and re-plan:

```bash
uv run yoto-iconer titles <cardId> --needs-query -o titles.json
# the LLM writes queries.json: {"<slot>": "<english search terms>"}
uv run yoto-iconer plan <cardId> --queries queries.json -o plan.json
```

Query terms should describe what the song is *about* in concrete, picturable
nouns. `--queries` also overrides English titles, which is useful when the
title is a metaphor.

## Commands

| Command | What it does |
|---|---|
| `setup [--client-id ID]` | print the client setup steps, or store the id |
| `login [--no-browser]` | OAuth2 PKCE sign-in via loopback |
| `status` | client id, login state, catalog contents |
| `cards` | list your MYO cards with their ids |
| `catalog sync [--official\|--community\|--user] [--pages N]` | build the local catalog |
| `catalog stats` | what is in the catalog |
| `search QUERY [-n N] [--source S] [--live]` | rank icons for one query |
| `titles CARD [--needs-query] [-o FILE]` | slot → title, for a translation pass |
| `plan CARD [-n N] [-o FILE] [--only-missing] [--no-live] [--text] [--queries F]` | the LLM's input |
| `show CARD` | current track → icon mapping |
| `apply [CARD] -d FILE [-p PLAN] [--dry-run]` | write icons back |

Every command takes `--json`.

## The decisions file

```json
{
  "cardId": "abc123",
  "assignments": [
    { "t": "01",    "icon": "i7",              "why": "school bus - 'Wheels on the Bus'" },
    { "t": "02.03", "icon": "yotoicons:1346",  "why": "dinosaur" },
    { "t": "02.04", "icon": "yoto:#WsZrlAbV…", "why": "known mediaId" }
  ]
}
```

* `t` is the slot id from the plan: `"01"` for a chapter, `"01.03"` for a track.
  A chapter slot with exactly one track stamps both, so the icon shows while the
  audio plays.
* `icon` accepts a plan short id (needs `-p plan.json`), `yotoicons:<id>`, a
  catalog key like `official:<mediaId>`, or a raw `yoto:#<mediaId>`.
* Omit a track to leave it untouched. `why` is ignored by the tool; it is there
  so the diff is reviewable.

## Safety

Yoto has no partial-update endpoint — a card is saved by POSTing the whole
content object back. So `apply` round-trips the exact object it fetched and
mutates only `display.icon16x16`; every other field, known or not, is preserved
byte for byte. Before any write the pre-change card is saved to
`~/.config/yoto-iconer/backups/<cardId>-<timestamp>.json`. `--dry-run` prints
the per-track diff and exits without uploading or writing anything. A single
unresolvable icon is reported and skipped rather than aborting the batch.

## Layout

```
~/.config/yoto-iconer/
  config.json      client id
  tokens.json      refresh + access token (0600)
  catalog.sqlite   icons, FTS5 index, upload dedupe cache
  cache/           scraped pages and PNGs
  backups/         pre-change card snapshots
```

Override the root with `YOTO_ICONER_HOME`, and the client id with
`YOTO_CLIENT_ID`.

## Tests

```bash
uv run pytest
```

No network, no account: the suite runs against fixtures and monkeypatched
transports.

## Caveat

yotoicons.com is a community site with no official API, so the scraper is
inherently unofficial and could break if the site's markup changes. The official
Yoto icon set never depends on it — `catalog sync --official` plus
`plan --no-live --source official` is a fully first-party fallback.

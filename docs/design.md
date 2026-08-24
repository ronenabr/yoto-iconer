# Design: yoto-iconer

## Problem

A Yoto MYO playlist has one icon slot per chapter and per track. Choosing an
icon per song is a semantic judgement (a job for an LLM) wrapped in a lot of
mechanical work (OAuth, catalog search, image upload, card round-tripping) that
an LLM should not be doing token by token. The naive approach — dump an icon
catalog into the model's context, or drive the Yoto web UI — is either
enormously expensive or unusable from a terminal.

## Shape

A zero-dependency Python CLI. `uv` manages the environment; the package itself
uses only `urllib`, `sqlite3` (FTS5) and `http.server`, so there is nothing to
break at install time and the whole implementation fits in one context window.

State lives in `~/.config/yoto-iconer/` (`YOTO_ICONER_HOME` overrides).

## Modules

| Module | Responsibility |
|---|---|
| `config` | paths, endpoints, scopes, client id resolution |
| `auth` | OAuth2 PKCE loopback login; silent refresh; 0600 token store |
| `api` | thin Yoto REST client (content read/write, icon list/upload) |
| `yotoicons` | polite, cached scraper for the community icon site |
| `catalog` | SQLite store + FTS5 index + upload dedupe cache |
| `search` | title → query normalization, ranking, stemming |
| `plan` | the compact LLM-facing document |
| `apply` | icon reference → mediaId, card patching, backup, write |
| `cli` | argparse front end |

Each is independently testable; only `cli` knows about all of them.

## The plan document

The efficiency of the whole tool lives here. For a whole playlist it emits one
JSON object:

- candidate icons appear **once** in a shared `icons` pool keyed by a
  two-character id, so a 43-character mediaId is never repeated;
- each icon is a `source|name|tags` string — never image data;
- a chapter with exactly one track collapses to a single slot, halving the rows
  for the common "one song per chapter" MYO card;
- `keys` maps short ids back to catalog keys so `apply` can resolve decisions.

A twelve-track playlist with six candidates each is ~1.6k tokens. Forty tracks
land in the 2-4k range, read once, answered once.

## Matching

Track titles are normalized (drop `(feat. …)`, `[Official Video]`, leading track
numbers, stopwords), then queried against FTS5. Ranking is bm25 plus explainable
boosts: name overlap, tag overlap, a bonus for icons that already have a
mediaId (official or already uploaded), and a log-scaled popularity term for
community icons. A crude stemmer keeps `star`/`stars` together, matching what
porter does inside FTS5.

When the local catalog's best hit does not share a word with the track's *name*
— a *Magic School Bus* icon merely tagged "dinosaurs" is not a dinosaur icon —
planning does a live yotoicons tag lookup on the title's most distinctive
tokens and folds the results into the catalog.

## Writing back

Yoto has no partial-update endpoint: a card is saved by POSTing the whole
content object. `apply` therefore round-trips the exact object it fetched and
mutates only `display.icon16x16`. The pre-change card is written to `backups/`
before any POST, `--dry-run` shows the per-track diff without uploading
anything, and one unresolvable icon is reported and skipped rather than
aborting the batch.

Community icons are uploaded lazily — only for icons actually chosen — and
deduplicated by SHA-256 of the PNG, so re-running never re-uploads.

## Known risk

yotoicons.com has no API, so the scraper is unofficial and could break with a
markup change. The official Yoto icon set never depends on it:
`catalog sync --official` with `plan --no-live --source official` is a fully
first-party fallback.

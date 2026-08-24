# Working in this repo

`yoto-iconer` matches Yoto MYO playlist tracks to display icons. The CLI does
the plumbing; the LLM only makes the judgement call.

## The matching loop

```bash
uv run yoto-iconer cards                              # find the cardId
uv run yoto-iconer plan <cardId> -o plan.json         # read this once
# choose an icon per track, write decisions.json
uv run yoto-iconer apply -d decisions.json -p plan.json --dry-run
uv run yoto-iconer apply -d decisions.json -p plan.json
```

Read `plan.json` in full — it is built to be small. Do **not** run `search` per
track before reading the plan; the plan already contains the candidates. Reach
for `search --live "<term>"` only for the specific tracks whose candidates are
all wrong, then rerun `plan` or reference the icon directly as
`yotoicons:<id>`.

`plan.json` fields: `icons` maps a short id to `source|name|tags`
(`off`=official Yoto, `com`=yotoicons.com community, `usr`=your uploads);
`tracks[].t` is the slot (`"01"` chapter, `"01.03"` track), `.q` the derived
query, `.c` the candidate short ids, `.now` the current icon if any.

Prefer `off` candidates when they are as good as a `com` one — they need no
upload. Always `--dry-run` before the real apply.

## Conventions

- Standard library only in `yoto_iconer/`. `uv` manages the environment; new
  dev-only tooling goes in the `dev` dependency group.
- `uv run pytest` must pass and must not touch the network or a real account:
  tests use fixtures and monkeypatched transports, and `conftest.py` redirects
  `YOTO_ICONER_HOME` to a tmp dir.
- Anything that writes to a card goes through `apply.patch_card`, which mutates
  only `display.icon16x16` and preserves every other field.

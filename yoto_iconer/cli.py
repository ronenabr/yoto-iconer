"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys

from . import api, apply as apply_mod, auth, catalog, config, plan as plan_mod, search, yotoicons

SETUP_STEPS = """\
Creating your Yoto API client (one time, ~2 minutes)

  1. Open https://dashboard.yoto.dev/ and sign in with the same account
     your Yoto app uses.
  2. Create a new application. Choose client type: PUBLIC.
     A public client is required - this tool holds no client secret.
  3. Register this exact redirect URL on the client:

         {redirect}

  4. Enable these scopes:

         user:content:manage    (read + write your MYO playlists)
         user:icons:manage      (upload community icons to your library)
         offline_access         (stay signed in between runs)

  5. Copy the Client ID and run:

         yoto-iconer setup --client-id <YOUR-CLIENT-ID>
         yoto-iconer login

Verification is not required for personal use.
"""


def _out(obj, as_json: bool, text: str | None = None) -> None:
    if as_json or text is None:
        print(json.dumps(obj, indent=2))
    else:
        print(text)


def _conn():
    return catalog.connect()


def _token() -> str:
    return auth.access_token()


# --- commands ----------------------------------------------------------------


def cmd_setup(args) -> int:
    if not args.client_id:
        print(SETUP_STEPS.format(redirect=config.REDIRECT_URI))
        current = config.client_id()
        print(f"Current client id: {current or '(none configured)'}")
        return 0
    cfg = config.load_config()
    cfg["client_id"] = args.client_id.strip()
    config.save_config(cfg)
    print(f"Saved client id to {config.config_path()}")
    print("Next: yoto-iconer login")
    return 0


def cmd_login(args) -> int:
    cid = config.client_id()
    if not cid:
        print(SETUP_STEPS.format(redirect=config.REDIRECT_URI), file=sys.stderr)
        return 2
    tokens = auth.login(cid, open_browser=not args.no_browser)
    print(f"Logged in. Tokens stored in {config.tokens_path()}")
    print(f"Scopes: {tokens.get('scope')}")
    return 0


def cmd_status(args) -> int:
    tokens = auth.load_tokens()
    info = {
        "home": str(config.home()),
        "clientId": config.client_id(),
        "loggedIn": bool(tokens.get("refresh_token")),
        "accessTokenExpiresAt": tokens.get("expires_at"),
        "catalog": catalog.stats(_conn()),
    }
    _out(info, args.json, text=None if args.json else json.dumps(info, indent=2))
    return 0


def cmd_cards(args) -> int:
    cards = api.list_cards(_token())
    rows = []
    for c in cards:
        chapters = ((c.get("content") or {}).get("chapters")) or []
        rows.append(
            {
                "cardId": c.get("cardId") or c.get("id"),
                "title": c.get("title"),
                "chapters": len(chapters),
                "tracks": sum(len(ch.get("tracks") or []) for ch in chapters),
            }
        )
    text = "\n".join(
        f"{r['cardId']}  {r['title']}  ({r['chapters']} ch / {r['tracks']} tr)" for r in rows
    )
    _out(rows, args.json, text or "No MYO cards found.")
    return 0


def cmd_catalog_sync(args) -> int:
    conn = _conn()
    want_official = args.official or not (args.official or args.community or args.user)
    want_community = args.community or not (args.official or args.community or args.user)
    totals = {}
    if want_official:
        totals["official"] = catalog.sync_official(conn, _token())
        print(f"official: {totals['official']} icons")
    if args.user:
        totals["user"] = catalog.sync_user(conn, _token())
        print(f"user: {totals['user']} icons")
    if want_community:
        def progress(page, pages, seen):
            print(f"\rcommunity: page {page}/{pages} ({seen} icons)", end="", flush=True)

        totals["community"] = catalog.sync_community(conn, args.pages, progress=progress)
        print(f"\rcommunity: {totals['community']} icons{' ' * 20}")
    _out(totals, args.json, text=None if args.json else "Catalog updated.")
    return 0


def cmd_catalog_stats(args) -> int:
    stats = catalog.stats(_conn())
    _out(stats, args.json, json.dumps(stats, indent=2))
    return 0


def cmd_search(args) -> int:
    conn = _conn()
    if args.live:
        for token in search.tokenize(args.query)[:2] or [args.query]:
            try:
                catalog.absorb_community_search(conn, token)
            except yotoicons.ScrapeError as exc:
                print(f"(live lookup failed: {exc})", file=sys.stderr)
    sources = tuple(args.source) if args.source else None
    hits = search.search(conn, args.query, limit=args.limit, sources=sources)
    slim = [
        {
            "key": h["key"],
            "ref": "yotoicons:" + h["ref"] if h["source"] == "community" else f"yoto:#{h['ref']}",
            "source": h["source"],
            "title": h["title"],
            "tags": h["tags"],
            "score": h["score"],
        }
        for h in hits
    ]
    text = "\n".join(
        f"{s['score']:>6}  {s['ref']:<52} [{s['source'][:3]}] {s['title']}  ~ {s['tags']}"
        for s in slim
    )
    _out(slim, args.json, text or "No matches. Try `--live` or a broader query.")
    return 0


def cmd_plan(args) -> int:
    conn = _conn()
    card = api.get_card(_token(), args.card_id)
    built = plan_mod.build(
        conn,
        card,
        limit=args.limit,
        sources=tuple(args.source) if args.source else None,
        only_missing=args.only_missing,
        live=not args.no_live,
    )
    payload = json.dumps(built, indent=1)
    if args.output:
        with open(args.output, "w") as fh:
            fh.write(payload + "\n")
        print(f"Wrote {args.output}  ({len(built['tracks'])} slots, {len(built['icons'])} icons)")
        if args.text:
            print()
            print(plan_mod.render_text(built))
        return 0
    print(plan_mod.render_text(built) if args.text else payload)
    return 0


def cmd_show(args) -> int:
    conn = _conn()
    card = api.get_card(_token(), args.card_id)
    rows = [
        {"t": slot, "title": title, "icon": icon,
         "name": plan_mod.describe_current(conn, icon)}
        for slot, title, icon, _both in plan_mod.iter_slots(card)
    ]
    text = "\n".join(
        f"{r['t']:>7}  {r['title'][:48]:<48} {r['name'] or '-'}" for r in rows
    )
    _out(rows, args.json, text)
    return 0


def cmd_apply(args) -> int:
    conn = _conn()
    decisions = json.loads(open(args.decisions).read())
    built = json.loads(open(args.plan).read()) if args.plan else None
    if args.card_id:
        decisions["cardId"] = args.card_id
    result = apply_mod.run(conn, _token(), decisions, built, dry_run=args.dry_run)

    lines = []
    for ch in result["changes"]:
        old = (ch["old"] or "-")[:20]
        lines.append(f"{ch['slot']:>7} {ch['level'][:2]}  {(ch['title'] or '')[:40]:<40} {old} -> {ch['new'][:20]}")
    for p in result["problems"]:
        lines.append(f"{p['slot']:>7} !!  {p['icon']}: {p['error']}")
    if result["uploads"]:
        lines.append(f"\nuploaded {len(result['uploads'])} community icon(s)")
    if result.get("backup"):
        lines.append(f"backup: {result['backup']}")
    lines.append("DRY RUN - nothing written" if args.dry_run else "Card updated.")
    _out(result, args.json, "\n".join(lines))
    return 1 if result["problems"] else 0


# --- parser ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="yoto-iconer",
        description="Match Yoto playlist tracks to display icons, LLM in the loop.",
    )
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("setup", help="show client setup steps / store a client id")
    s.add_argument("--client-id")
    s.set_defaults(func=cmd_setup)

    s = sub.add_parser("login", help="sign in via browser (OAuth2 PKCE)")
    s.add_argument("--no-browser", action="store_true", help="print the URL, do not open it")
    s.set_defaults(func=cmd_login)

    s = sub.add_parser("status", help="show auth and catalog state")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("cards", help="list your MYO cards")
    s.set_defaults(func=cmd_cards)

    s = sub.add_parser("catalog", help="manage the local icon catalog")
    csub = s.add_subparsers(dest="subcommand", required=True)
    cs = csub.add_parser("sync", help="download icon metadata")
    cs.add_argument("--official", action="store_true", help="official Yoto icon set")
    cs.add_argument("--community", action="store_true", help="yotoicons.com")
    cs.add_argument("--user", action="store_true", help="your own uploaded icons")
    cs.add_argument("--pages", type=int, default=120,
                    help="yotoicons pages to crawl, 25 icons each (default: 120)")
    cs.set_defaults(func=cmd_catalog_sync)
    cs = csub.add_parser("stats", help="what is in the catalog")
    cs.set_defaults(func=cmd_catalog_stats)

    s = sub.add_parser("search", help="search the icon catalog")
    s.add_argument("query")
    s.add_argument("-n", "--limit", type=int, default=8)
    s.add_argument("--source", action="append", choices=["official", "community", "user"])
    s.add_argument("--live", action="store_true", help="also query yotoicons.com now")
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("plan", help="emit the compact match plan for an LLM")
    s.add_argument("card_id")
    s.add_argument("-n", "--limit", type=int, default=8, help="candidates per track")
    s.add_argument("-o", "--output")
    s.add_argument("--source", action="append", choices=["official", "community", "user"])
    s.add_argument("--only-missing", action="store_true", help="skip tracks that already have icons")
    s.add_argument("--no-live", action="store_true", help="never hit yotoicons.com while planning")
    s.add_argument("--text", action="store_true", help="human-readable rendering")
    s.set_defaults(func=cmd_plan)

    s = sub.add_parser("show", help="show the current track -> icon mapping")
    s.add_argument("card_id")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("apply", help="write chosen icons back to the card")
    s.add_argument("card_id", nargs="?")
    s.add_argument("-d", "--decisions", required=True)
    s.add_argument("-p", "--plan", help="the plan file, so short icon ids resolve")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_apply)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (auth.AuthError, api.ApiError, apply_mod.ApplyError, yotoicons.ScrapeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

"""Build the compact match plan an LLM reads, and its human-readable form."""

from __future__ import annotations

import sqlite3
import time

from . import catalog, search, yotoicons

SOURCE_ABBR = {"official": "off", "community": "com", "user": "usr"}
WEAK_SCORE = 6.0  # below this the local catalog probably has nothing good
MAX_ENTRY = 72    # community icons carry very long tag strings; cap what the LLM reads


def _entry(cand: dict) -> str:
    """One icon as `source|name|tags`, trimmed so long tag lists stay cheap."""
    src = SOURCE_ABBR.get(cand["source"], cand["source"])
    title = cand["title"]
    tags = cand["tags"]
    # Tags that merely restate the name earn nothing.
    if tags and tags.lower() == title.lower():
        tags = ""
    entry = "|".join([src, title, tags]).rstrip("|")
    return entry if len(entry) <= MAX_ENTRY else entry[:MAX_ENTRY - 1] + "\u2026"


def for_llm(built: dict) -> dict:
    """The plan minus the bits only `apply` needs."""
    return {k: v for k, v in built.items() if k not in ("keys", "generated")}


def iter_slots(card: dict, only_missing: bool = False):
    """Yield (slot_id, title, current_icon, applies_to_both) for a card.

    A chapter holding a single track collapses into one slot, because MYO cards
    built from audio files almost always look like that and the icon should go
    on both.
    """
    chapters = ((card.get("content") or {}).get("chapters")) or []
    for chapter in chapters:
        ckey = str(chapter.get("key") or "")
        tracks = chapter.get("tracks") or []
        cicon = ((chapter.get("display") or {}).get("icon16x16")) or None

        if len(tracks) == 1:
            track = tracks[0]
            ticon = ((track.get("display") or {}).get("icon16x16")) or None
            title = track.get("title") or chapter.get("title") or ckey
            icon = ticon or cicon
            if not (only_missing and icon):
                yield ckey, title, icon, True
            continue

        if not (only_missing and cicon):
            yield ckey, chapter.get("title") or ckey, cicon, False
        for track in tracks:
            tkey = str(track.get("key") or "")
            ticon = ((track.get("display") or {}).get("icon16x16")) or None
            if only_missing and ticon:
                continue
            yield f"{ckey}.{tkey}", track.get("title") or tkey, ticon, False


def describe_current(conn: sqlite3.Connection, icon: str | None) -> str | None:
    if not icon:
        return None
    media_id = icon.split("#", 1)[-1]
    row = conn.execute(
        "SELECT title FROM icons WHERE media_id = ? LIMIT 1", (media_id,)
    ).fetchone()
    return row["title"] if row else "custom"


def build(
    conn: sqlite3.Connection,
    card: dict,
    limit: int = 8,
    sources: tuple[str, ...] | None = None,
    only_missing: bool = False,
    live: bool = True,
    queries: dict[str, str] | None = None,
) -> dict:
    pool: dict[str, str] = {}   # icon key -> short id
    icons: dict[str, str] = {}  # short id -> "src|title|tags"
    rows = []

    queries = queries or {}
    for slot, title, current, both in iter_slots(card, only_missing=only_missing):
        supplied = (queries.get(slot) or "").strip()
        # A non-Latin title cannot be searched against English-tagged icons;
        # it needs a translated query before candidates mean anything.
        if not supplied and not search.is_latin(title):
            rows.append({"t": slot, "title": title, "q": "", "c": [], "needs": "q"})
            continue

        query = supplied or search.query_for(title)
        candidates = search.search(conn, query, limit=limit, sources=sources)

        tokens = search.tokenize(query)
        # A high bm25 score on a near-miss is not a match: insist on a real
        # word overlap before trusting the local catalog.
        needs_help = (
            not candidates
            or candidates[0]["score"] < WEAK_SCORE
            or not search.title_hit(candidates[0], tokens)
        )
        if live and needs_help and (not sources or "community" in sources):
            for token in search.live_terms(query):
                try:
                    catalog.absorb_community_search(conn, token)
                except yotoicons.ScrapeError:
                    break
            candidates = search.search(conn, query, limit=limit, sources=sources)

        short_ids = []
        for cand in candidates:
            sid = pool.get(cand["key"])
            if sid is None:
                sid = f"i{len(pool) + 1}"
                pool[cand["key"]] = sid
                icons[sid] = _entry(cand)
            short_ids.append(sid)

        row = {"t": slot, "title": title, "q": query, "c": short_ids}
        if both:
            row["both"] = 1
        if (now := describe_current(conn, current)):
            row["now"] = now
        rows.append(row)

    return {
        "cardId": card.get("cardId") or card.get("id"),
        "cardTitle": card.get("title"),
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "howto": (
            "Pick the icon that best pictures each track title. Reply with a decisions "
            "file: {\"cardId\": ..., \"assignments\": [{\"t\": <t>, \"icon\": <short id "
            "from icons, or 'yotoicons:<numeric id>', or 'yoto:#<mediaId>'>, \"why\": "
            "\"...\"}]}. Omit a track to leave it untouched. Icon values read "
            "'source|name|tags' where off=official Yoto icon, com=yotoicons.com "
            "community icon, usr=your own uploaded icon. A track marked needs=q has a "
            "non-English title: supply English search terms for it via "
            "`plan --queries` and re-plan."
        ),
        "keys": {pool[k]: k for k in pool},
        "icons": icons,
        "tracks": rows,
    }


def render_text(plan: dict, per_track: int = 5) -> str:
    """Terminal view of a plan - one line per track, candidates inline."""
    lines = [f"{plan.get('cardTitle')}  [{plan.get('cardId')}]", ""]
    icons = plan["icons"]
    for row in plan["tracks"]:
        current = f"  (now: {row['now']})" if row.get("now") else ""
        lines.append(f"{row['t']:>7}  {row['title']}{current}")
        if row.get("needs") == "q":
            lines.append("          needs an English query - see `yoto-iconer titles`")
            lines.append("")
            continue
        if not row["c"]:
            lines.append("          no candidates - try `yoto-iconer search`")
        for sid in row["c"][:per_track]:
            src, _, rest = icons[sid].partition("|")
            lines.append(f"          {sid:>5}  [{src}] {rest.replace('|', '  ~ ')}")
        lines.append("")
    return "\n".join(lines)

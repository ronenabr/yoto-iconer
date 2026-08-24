"""Resolve chosen icons to mediaIds and write them back onto a card."""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import time
from pathlib import Path

from . import api, catalog, config, yotoicons


class ApplyError(Exception):
    pass


# --- resolving an icon reference to a Yoto mediaId ---------------------------


def resolve_key(spec: str, plan: dict | None) -> str:
    """Map whatever the LLM wrote to a catalog key or a direct 'yoto:#...' ref."""
    spec = (spec or "").strip()
    if not spec:
        raise ApplyError("empty icon reference")
    if spec.startswith("yoto:"):
        return "yoto:#" + spec.split("#", 1)[-1].lstrip("#")
    if spec.startswith("yotoicons:"):
        return "community:" + spec.split(":", 1)[1]
    if spec.split(":", 1)[0] in ("official", "community", "user"):
        return spec
    if plan and spec in (plan.get("keys") or {}):
        return plan["keys"][spec]
    raise ApplyError(
        f"unknown icon reference {spec!r} - pass --plan so short ids resolve, "
        "or use 'yotoicons:<id>' / 'yoto:#<mediaId>'"
    )


def media_id_for(
    conn: sqlite3.Connection, key: str, token: str, dry_run: bool = False
) -> tuple[str, bool]:
    """Return (mediaId, uploaded_now). Uploads community icons on demand."""
    if key.startswith("yoto:#"):
        return key.split("#", 1)[1], False

    row = catalog.get(conn, key)
    if row is None:
        if not key.startswith("community:"):
            raise ApplyError(f"{key} is not in the local catalog - run `catalog sync`")
        # Known-good pattern: a community id we have never indexed.
        icon_id = key.split(":", 1)[1]
        catalog.upsert(
            conn,
            [
                catalog.community_record(
                    {"id": icon_id, "title": f"yotoicons {icon_id}", "tags": [],
                     "category": "", "artist": "", "downloads": 0}
                )
            ],
        )
        row = catalog.get(conn, key)

    if row["media_id"]:
        return row["media_id"], False
    if row["source"] != "community":
        raise ApplyError(f"{key} has no mediaId and is not uploadable")

    if dry_run:
        return f"<upload {key}>", True

    png = yotoicons.download_png(row["ref"])
    sha = hashlib.sha256(png).hexdigest()
    if (cached := catalog.upload_for_sha(conn, sha)):
        catalog.set_media_id(conn, key, cached)
        return cached, False

    media_id = api.upload_icon(token, png, f"yotoicons-{row['ref']}.png")
    catalog.remember_upload(conn, sha, media_id)
    catalog.set_media_id(conn, key, media_id)
    return media_id, True


# --- patching the card -------------------------------------------------------


def _set_icon(node: dict, media_id: str) -> str | None:
    display = node.get("display")
    if not isinstance(display, dict):
        display = {}
        node["display"] = display
    old = display.get("icon16x16")
    display["icon16x16"] = f"yoto:#{media_id}"
    return old


def patch_card(card: dict, assignments: dict[str, str]) -> list[dict]:
    """Apply {slot: mediaId} onto a card in place; returns a change log.

    A chapter slot with exactly one track also stamps that track, so the icon
    actually shows while the audio plays.
    """
    chapters = ((card.get("content") or {}).get("chapters")) or []
    changes: list[dict] = []
    seen: set[str] = set()

    for chapter in chapters:
        ckey = str(chapter.get("key") or "")
        tracks = chapter.get("tracks") or []

        if ckey in assignments:
            media_id = assignments[ckey]
            seen.add(ckey)
            old = _set_icon(chapter, media_id)
            changes.append(
                {"slot": ckey, "title": chapter.get("title"), "old": old,
                 "new": f"yoto:#{media_id}", "level": "chapter"}
            )
            if len(tracks) == 1:
                old = _set_icon(tracks[0], media_id)
                changes.append(
                    {"slot": ckey, "title": tracks[0].get("title"), "old": old,
                     "new": f"yoto:#{media_id}", "level": "track"}
                )

        for track in tracks:
            slot = f"{ckey}.{track.get('key')}"
            if slot not in assignments:
                continue
            media_id = assignments[slot]
            seen.add(slot)
            old = _set_icon(track, media_id)
            changes.append(
                {"slot": slot, "title": track.get("title"), "old": old,
                 "new": f"yoto:#{media_id}", "level": "track"}
            )

    missing = sorted(set(assignments) - seen)
    if missing:
        raise ApplyError(f"no such track/chapter on this card: {', '.join(missing)}")
    return changes


def backup(card: dict) -> Path:
    d = config.backups_dir()
    d.mkdir(parents=True, exist_ok=True)
    name = f"{card.get('cardId') or 'card'}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path = d / name
    path.write_text(json.dumps(card, indent=2))
    return path


def run(
    conn: sqlite3.Connection,
    token: str,
    decisions: dict,
    plan: dict | None,
    dry_run: bool = False,
    card: dict | None = None,
) -> dict:
    card_id = decisions.get("cardId") or (plan or {}).get("cardId")
    if not card_id:
        raise ApplyError("decisions file has no cardId")

    if card is None:
        card = api.get_card(token, card_id)
    original = copy.deepcopy(card)

    resolved: dict[str, str] = {}
    uploads: list[str] = []
    problems: list[dict] = []

    for item in decisions.get("assignments") or []:
        slot = str(item.get("t") or item.get("track") or "")
        try:
            key = resolve_key(item.get("icon", ""), plan)
            media_id, uploaded = media_id_for(conn, key, token, dry_run=dry_run)
        except (ApplyError, api.ApiError, yotoicons.ScrapeError) as exc:
            # One bad icon must not sink the whole playlist.
            problems.append({"slot": slot, "icon": item.get("icon"), "error": str(exc)})
            continue
        resolved[slot] = media_id
        if uploaded:
            uploads.append(key)

    changes = patch_card(card, resolved)

    result = {
        "cardId": card_id,
        "changes": changes,
        "uploads": uploads,
        "problems": problems,
        "dryRun": dry_run,
    }
    if dry_run or not changes:
        return result

    result["backup"] = str(backup(original))
    api.update_card(token, card)
    result["applied"] = True
    return result
